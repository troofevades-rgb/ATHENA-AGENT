/**
 * Pure reducer over TuiState.
 *
 * The action set is intentionally narrow:
 *   - One `EVENT` action for every gateway → TUI frame (the transport
 *     layer wraps the gateway event)
 *   - A handful of UI-local actions for keyboard-driven state changes
 *     (append separator, dismiss flash, dismiss confirm)
 *
 * The transcript renders through Ink's <Static> (see Transcript.tsx),
 * so `lines` is APPEND-ONLY and there is no app-managed scroll — the
 * terminal owns scrollback. Multi-line content is still split into one
 * TranscriptLine per row at commit time (keeps the per-row diff/code/
 * file:line classification simple).
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

/**
 * Append a single transcript line. APPEND-ONLY: the transcript renders
 * via Ink's <Static>, which prints each line once into terminal
 * scrollback and tracks how many it has emitted by array index —
 * front-trimming would shift that index and silently drop output. See
 * LINES_CAP in types.ts.
 */
function appendLine(
  lines: TuiState["lines"],
  newLine: TranscriptLine,
): TuiState["lines"] {
  return [...lines, newLine];
}

/**
 * Append multiple transcript lines. Append-only (see appendLine).
 * Each entry = one terminal row.
 */
function appendLines(
  lines: TuiState["lines"],
  newLines: TranscriptLine[],
): TuiState["lines"] {
  if (newLines.length === 0) return lines;
  return [...lines, ...newLines];
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
  | { type: "TOGGLE_REASONING" }
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
      };
    }

    case "DISMISS_FLASH":
      return { ...state, flash: null };

    case "DISMISS_CONFIRM":
      return { ...state, confirmReq: null };

    case "DISMISS_ASK":
      return { ...state, askReq: null };

    case "TOGGLE_REASONING": {
      // Forward-looking: flips the flag and confirms via a flash, since
      // the change only affects thoughts that commit after this point
      // (committed <Static> lines can't re-render). Reuses the existing
      // flash channel so feedback is immediate and self-dismissing.
      const next = !state.showReasoning;
      const flash: StatusFlashEvent = {
        type: "status.flash",
        level: "info",
        text: next ? "reasoning shown" : "reasoning hidden",
        ttl_seconds: 2,
      };
      return { ...state, showReasoning: next, flash };
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
      // Assistant text is held as ONE line carrying the full content and
      // rendered as a multi-row markdown block (renderLine → <Markdown>:
      // headings, lists, fenced code, emphasis). Other roles stay
      // one-row-per-line (user gets the ▸▸ prefix, system the dot).
      if (e.role === "assistant") {
        const k = nextKey(state);
        return withProgress({
          ...state,
          lines: appendLine(state.lines, {
            key: k.key, role: "assistant", content: e.content,
          }),
          _nextKey: k._nextKey,
        });
      }
      const { rows, nextKey: nk } = splitToRows(
        e.content, e.role, state._nextKey,
      );
      return withProgress({
        ...state,
        lines: appendLines(state.lines, rows),
        _nextKey: nk,
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
      const rows: TranscriptLine[] = [];
      let nk = state._nextKey;
      // Reasoning, when toggled on: a "▾ thinking (N lines)" header
      // plus the dim body, committed BEFORE the answer. Forward-looking
      // by construction — we only have e.thinking for thoughts that
      // commit while the flag is on.
      const thinking = (e.thinking ?? "").trim();
      if (state.showReasoning && thinking.length > 0) {
        const tlines = thinking.split("\n");
        rows.push({
          key: nk++, role: "thinking",
          content: `▾ thinking (${tlines.length} line${tlines.length === 1 ? "" : "s"})`,
        });
        for (const tl of tlines) {
          rows.push({ key: nk++, role: "thinking", content: `  ${tl}` });
        }
      }
      if (hasContent) {
        // One line holding the full reply; renderLine renders it as a
        // multi-row markdown block. (See message.append above.)
        rows.push({ key: nk++, role: "assistant", content: finalText });
      }
      return withProgress({
        ...state,
        lines: appendLines(state.lines, rows),
        _nextKey: nk,
        streaming: "",
        _streamFilter: initialThinkFilterState,
        streamId: null,
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
      // Split tool result into individual rows, Claude-Code-tree style:
      //   row 0:  "⏺ Tool(args)  dur"  (header, ⏺ = status dot)
      //   row 1:  "⎿ line"             (first output line, branch glyph)
      //   row 2+: "  line"             (continuation, capped at 12 lines)
      const bodyText = truncate(e.result_preview, 2000);
      const bodyLines = bodyText.split("\n");
      const MAX_BODY = 12;
      const shown = bodyLines.slice(0, MAX_BODY);
      const overflow = bodyLines.length - MAX_BODY;

      const rows: TranscriptLine[] = [];
      let key = state._nextKey;
      // Header — "⏺ Tool(args)  dur". Args come from the matching
      // tool.start lane entry (removed from the lane just below); the ⏺
      // marker is colored as a status dot by renderLine. A dim duration
      // suffix is appended when the backend timed the dispatch.
      // Pair strictly by call_id. The dispatch layer assigns a unique
      // id per call, so several concurrent calls of the SAME tool each
      // keep their own lane row. (A `t.tool === e.tool` fallback used to
      // live here from when start/complete ids didn't match; under
      // parallel dispatch it mass-evicted every same-named call on the
      // first completion, so it's gone.)
      const laneEntry = state.toolLane.find((t) => t.id === e.call_id);
      const argsRaw = laneEntry?.args ?? "";
      const args = argsRaw.length > 40 ? argsRaw.slice(0, 39) + "…" : argsRaw;
      const durSuffix = formatToolDuration(e.duration_ms);
      const header = `⏺ ${e.tool}${args ? `(${args})` : ""}`
        + (durSuffix ? `  ${durSuffix}` : "");
      rows.push({ key: key++, role: "tool", content: header });
      // Body lines — if this is a diff (tool name starts with
      // "diff " — see athena/ui.py:show_diff), classify each line
      // with the appropriate diff-* role so it renders with the
      // proper +/- color and hunk header treatment. Otherwise hang the
      // output off the header with a "⎿" branch on the first line.
      const isDiff = e.tool.startsWith("diff ");
      if (isDiff) {
        const diffRows = splitDiffContent(shown.join("\n"), key);
        for (const r of diffRows.rows) {
          rows.push({ ...r, content: `  ${r.content}` });
        }
        key = diffRows.nextKey;
      } else {
        shown.forEach((line, i) => {
          const gutter = i === 0 ? "⎿ " : "  ";
          rows.push({ key: key++, role: "tool", content: `${gutter}${line}` });
        });
      }
      if (overflow > 0) {
        rows.push({ key: key++, role: "tool", content: `  ... (${overflow} more lines)` });
      }

      return withProgress({
        ...state,
        toolLane: state.toolLane.filter((t) => t.id !== e.call_id),
        lines: appendLines(state.lines, rows),
        _nextKey: key,
      });
    }

    case "tool.progress":
      // Lifecycle event — counts as progress even though we don't
      // render anything from it.
      return withProgress(state);

    case "confirm.request":
      return { ...state, confirmReq: event as ConfirmRequestEvent };

    case "ask_question.request":
      return {
        ...state,
        askReq: event as import("../transport/protocol.js").AskQuestionRequestEvent,
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
