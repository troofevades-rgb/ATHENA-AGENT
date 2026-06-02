/**
 * Pure reducer over TuiState.
 *
 * The action set is intentionally narrow:
 *   - One `EVENT` action for every gateway → TUI frame (the transport
 *     layer wraps the gateway event)
 *   - A handful of UI-local actions for keyboard-driven state changes
 *     (scroll, append separator, dismiss flash, dismiss confirm)
 *
 * IMPORTANT: Every TranscriptLine = exactly one terminal row.
 * Multi-line content is split at commit time so the windowing
 * math (visibleBudget = terminal rows available) is trivially
 * correct. renderLine() in Transcript.tsx can rely on this
 * invariant and never return multi-row elements.
 */

import type {
  BannerEvent,
  ConfirmRequestEvent,
  Event,
  HelloEvent,
  MessageAppendEvent,
  ProtocolErrorEvent,
  StatusFlashEvent,
  StatusUpdateEvent,
  StreamDeltaEvent,
  StreamEndEvent,
  StreamStartEvent,
  ToolCompleteEvent,
  ToolStartEvent,
} from "../transport/protocol.js";
import { appendFilter, initialThinkFilterState } from "../stream/thinkBlocks.js";
import type { TuiState, TranscriptLine } from "./types.js";
import { LINES_CAP } from "./types.js";

/**
 * Append a single transcript line while keeping the array bounded.
 */
function appendLine(
  lines: TuiState["lines"],
  newLine: TranscriptLine,
): TuiState["lines"] {
  if (lines.length < LINES_CAP) return [...lines, newLine];
  return [...lines.slice(lines.length - LINES_CAP + 1), newLine];
}

/**
 * Append multiple transcript lines while keeping the array bounded.
 * Each entry = one terminal row.
 */
function appendLines(
  lines: TuiState["lines"],
  newLines: TranscriptLine[],
): TuiState["lines"] {
  if (newLines.length === 0) return lines;
  const combined = [...lines, ...newLines];
  if (combined.length <= LINES_CAP) return combined;
  return combined.slice(combined.length - LINES_CAP);
}

/**
 * Split content on newlines and produce one TranscriptLine per row.
 * Returns the lines array and the next key counter.
 *
 * For ``role === "assistant"``, scan for fenced code blocks
 * (``` ... ```) and mark lines inside as ``role: "code"`` so they
 * render with a left gutter + code styling. Fence delimiters
 * themselves are dropped (otherwise we'd show literal backticks).
 */
function splitToRows(
  content: string,
  role: TranscriptLine["role"],
  startKey: number,
): { rows: TranscriptLine[]; nextKey: number } {
  if (role === "assistant") {
    return splitAssistantContent(content, startKey);
  }
  const parts = content.split("\n");
  const rows: TranscriptLine[] = [];
  let key = startKey;
  for (const part of parts) {
    rows.push({ key, role, content: part });
    key++;
  }
  return { rows, nextKey: key };
}


/**
 * Assistant text splitter with fenced-code-block detection.
 *
 * Recognizes ``` fences at the start of a line (3 or more
 * backticks, optionally followed by a language tag). Lines inside
 * a fence get ``role: "code"``; the fence lines themselves are
 * dropped from display.
 */
export function splitAssistantContent(
  content: string,
  startKey: number,
): { rows: TranscriptLine[]; nextKey: number } {
  const parts = content.split("\n");
  const rows: TranscriptLine[] = [];
  let key = startKey;
  let inFence = false;
  for (const part of parts) {
    // Fence detection: trimmed line is 3+ backticks (optionally
    // followed by a language tag like "```python"). Anything else
    // is content.
    const trimmed = part.trimStart();
    if (/^```+/.test(trimmed)) {
      inFence = !inFence;
      // Drop the fence line itself — no value in rendering literal ```
      continue;
    }
    rows.push({
      key,
      role: inFence ? "code" : "assistant",
      content: part,
    });
    key++;
  }
  return { rows, nextKey: key };
}


/**
 * Classify each line of a unified diff into the appropriate role.
 *
 * Unified diff format:
 *   ``--- a/path``  →  diff-file
 *   ``+++ b/path``  →  diff-file
 *   ``@@ -5,3 +5,3 @@``  →  diff-hunk
 *   ``+ added text``  →  diff-add
 *   ``- removed text``  →  diff-del
 *   `` context text`` (leading space)  →  tool (treated as context)
 *
 * Used when a tool_complete arrives whose tool name signals diff
 * output (``tool: "diff <path>"``) — see reducer below.
 */
export function splitDiffContent(
  content: string,
  startKey: number,
): { rows: TranscriptLine[]; nextKey: number } {
  const parts = content.split("\n");
  const rows: TranscriptLine[] = [];
  let key = startKey;
  for (const part of parts) {
    let role: TranscriptLine["role"];
    if (part.startsWith("@@")) role = "diff-hunk";
    else if (part.startsWith("---") || part.startsWith("+++")) role = "diff-file";
    else if (part.startsWith("+")) role = "diff-add";
    else if (part.startsWith("-")) role = "diff-del";
    else role = "tool";  // context line; reuse tool styling for neutrality
    rows.push({ key, role, content: part });
    key++;
  }
  return { rows, nextKey: key };
}

export type Action =
  | { type: "EVENT"; event: Event }
  | { type: "SET_PROTOCOL_ERROR"; event: ProtocolErrorEvent | null }
  | { type: "SET_SERVER_HELLO"; event: HelloEvent | null }
  | { type: "APPEND_SEPARATOR"; content: string }
  | { type: "DISMISS_FLASH" }
  | { type: "DISMISS_CONFIRM" }
  | { type: "DISMISS_ASK" }
  | { type: "SET_SCROLL"; offset: number }
  | { type: "USER_INPUT_SENT" };

function nextKey(state: TuiState): {key: number, _nextKey: number} {
  return { key: state._nextKey, _nextKey: state._nextKey + 1 };
}

export function reducer(state: TuiState, action: Action): TuiState {
  switch (action.type) {
    case "SET_PROTOCOL_ERROR":
      return { ...state, protocolError: action.event };

    case "SET_SERVER_HELLO":
      return { ...state, serverHello: action.event };

    case "APPEND_SEPARATOR": {
      const k = nextKey(state);
      return {
        ...state,
        lines: appendLine(state.lines, {
          key: k.key, role: "separator", content: action.content,
        }),
        _nextKey: k._nextKey,
        scrollOffset: 0,
      };
    }

    case "DISMISS_FLASH":
      return { ...state, flash: null };

    case "DISMISS_CONFIRM":
      return { ...state, confirmReq: null };

    case "DISMISS_ASK":
      return { ...state, askReq: null };

    case "SET_SCROLL": {
      // Clamp both ends:
      //   - lower bound 0 (can't scroll BELOW the bottom)
      //   - upper bound lines.length (can't scroll PAST the oldest
      //     committed line — otherwise repeated Shift+↑ or PageUp
      //     accumulates offset and a single PageDown can't get back
      //     to the bottom; the user has to PageDown N times)
      const maxOffset = Math.max(0, state.lines.length);
      const clamped = Math.min(maxOffset, Math.max(0, action.offset));
      return { ...state, scrollOffset: clamped };
    }

    case "USER_INPUT_SENT":
      // Begin tracking a pending response from this moment. Stuck
      // detector flips on if no progress event arrives in 30s.
      return {
        ...state,
        _pendingUserInputSince: performance.now(),
        _lastProgressMs: performance.now(),
      };

    case "EVENT":
      return reduceEvent(state, action.event);
  }
}

/** Bump _lastProgressMs and clear _pendingUserInputSince. Called by
 * every event that signals real agent/model work — NOT by status
 * heartbeats, which would mask a stalled stream. */
function withProgress<S extends TuiState>(state: S): S {
  return {
    ...state,
    _lastProgressMs: performance.now(),
    _pendingUserInputSince: null,
  };
}

function reduceEvent(state: TuiState, event: Event): TuiState {
  switch (event.type) {
    case "banner":
      return { ...state, banner: event as BannerEvent };

    case "status":
      return { ...state, status: event as StatusUpdateEvent };

    case "status.flash":
      return { ...state, flash: event as StatusFlashEvent };

    case "theme.change":
      return state.banner
        ? { ...state, banner: { ...state.banner, palette: event.palette } }
        : state;

    case "message.append": {
      const e = event as MessageAppendEvent;
      const wasAtBottom = state.scrollOffset === 0;
      const { rows, nextKey: nk } = splitToRows(
        e.content, e.role, state._nextKey,
      );
      return withProgress({
        ...state,
        lines: appendLines(state.lines, rows),
        _nextKey: nk,
        scrollOffset: wasAtBottom ? 0 : state.scrollOffset,
      });
    }

    case "stream.start": {
      const e = event as StreamStartEvent;
      return withProgress({
        ...state,
        streamId: e.stream_id,
        streaming: "",
        _streamFilter: initialThinkFilterState,
      });
    }

    case "stream.delta": {
      const e = event as StreamDeltaEvent;
      if (e.stream_id !== state.streamId) return state;
      const { state: nextFilter, popLen, append } = appendFilter(
        state._streamFilter,
        e.text,
      );
      const popped = popLen > 0
        ? state.streaming.slice(0, state.streaming.length - popLen)
        : state.streaming;
      return withProgress({
        ...state,
        streaming: append ? popped + append : popped,
        _streamFilter: nextFilter,
      });
    }

    case "stream.end": {
      const e = event as StreamEndEvent;
      if (e.stream_id !== state.streamId) return state;
      // Producer-provided polished view wins. The Python typewriter
      // sends the <think>-stripped text in ``final_text`` on
      // finalize so the transcript shows the clean version even
      // when streaming chunks contained raw thought tags. Legacy
      // producers (no final_text) fall back to the accumulated
      // buffer + the local thought-marker scrub.
      const rawText = state.streaming + (state._streamFilter.tail || "");
      const fallbackText = rawText.replace(/·\s*\(thought\)\s*/g, "").trim();
      const finalText = (e.final_text ?? fallbackText).trim();
      const hasContent = finalText.length > 0;
      const wasAtBottom = state.scrollOffset === 0;
      let newLines = state.lines;
      let nk = state._nextKey;
      if (hasContent) {
        const { rows, nextKey: nk2 } = splitToRows(
          finalText, "assistant", state._nextKey,
        );
        newLines = appendLines(state.lines, rows);
        nk = nk2;
      }
      return withProgress({
        ...state,
        lines: newLines,
        _nextKey: nk,
        streaming: "",
        _streamFilter: initialThinkFilterState,
        streamId: null,
        scrollOffset: wasAtBottom ? 0 : state.scrollOffset,
      });
    }

    case "tool.start": {
      const e = event as ToolStartEvent;
      return withProgress({
        ...state,
        toolLane: [
          ...state.toolLane,
          {
            id: e.call_id,
            tool: e.tool,
            args: e.args_preview,
            startedAtMs: performance.now(),
          },
        ],
      });
    }

    case "tool.complete": {
      const e = event as ToolCompleteEvent;
      const wasAtBottom = state.scrollOffset === 0;
      // Split tool result into individual rows:
      //   row 0:  "> toolName"  (header)
      //   row 1+: "  line"     (body, capped at 12 lines)
      const bodyText = truncate(e.result_preview, 2000);
      const bodyLines = bodyText.split("\n");
      const MAX_BODY = 12;
      const shown = bodyLines.slice(0, MAX_BODY);
      const overflow = bodyLines.length - MAX_BODY;

      const rows: TranscriptLine[] = [];
      let key = state._nextKey;
      // Header — append a dim duration suffix when the backend timed
      // the dispatch (sub-second → "123ms", else "1.2s").
      const durSuffix = formatToolDuration(e.duration_ms);
      rows.push({
        key: key++,
        role: "tool",
        content: durSuffix ? `> ${e.tool}  ${durSuffix}` : `> ${e.tool}`,
      });
      // Body lines — if this is a diff (tool name starts with
      // "diff " — see athena/ui.py:show_diff), classify each line
      // with the appropriate diff-* role so it renders with the
      // proper +/- color and hunk header treatment.
      const isDiff = e.tool.startsWith("diff ");
      if (isDiff) {
        const diffRows = splitDiffContent(shown.join("\n"), key);
        for (const r of diffRows.rows) {
          rows.push({ ...r, content: `  ${r.content}` });
        }
        key = diffRows.nextKey;
      } else {
        for (const line of shown) {
          rows.push({ key: key++, role: "tool", content: `  ${line}` });
        }
      }
      if (overflow > 0) {
        rows.push({ key: key++, role: "tool", content: `  ... (${overflow} more lines)` });
      }

      return withProgress({
        ...state,
        toolLane: state.toolLane.filter(
          (t) => t.id !== e.call_id && t.tool !== e.tool,
        ),
        lines: appendLines(state.lines, rows),
        _nextKey: key,
        scrollOffset: wasAtBottom ? 0 : state.scrollOffset,
      });
    }

    case "tool.progress":
      // Lifecycle event — counts as progress even though we don't
      // render anything from it.
      return withProgress(state);

    case "confirm.request":
      return { ...state, confirmReq: event as ConfirmRequestEvent, scrollOffset: 0 };

    case "ask_question.request":
      return {
        ...state,
        askReq: event as import("../transport/protocol.js").AskQuestionRequestEvent,
        scrollOffset: 0,
      };

    case "exit":
      return state;

    default:
      return state;
  }
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}

/** Format a tool dispatch duration for the result header. Sub-second →
 * "123ms"; otherwise "1.2s". Returns "" when there's nothing to show. */
function formatToolDuration(ms: number | undefined): string {
  if (ms == null || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
