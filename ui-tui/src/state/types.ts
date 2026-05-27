/**
 * TuiState — the single shape held by the app's reducer.
 *
 * Replaces the ~10 separate useState calls that lived in main.tsx
 * before step 8. All UI state lives in one tree; all mutations
 * funnel through the reducer. The renderer reads from one place.
 *
 * Why one big state instead of scattered useState: makes the data
 * flow `event → reduce → render` explicit, makes the state legible
 * to test fixtures, and makes future serialization (session replay,
 * web-dashboard mirror) trivial because the snapshot IS the state.
 */

import type {
  AskQuestionRequestEvent,
  BannerEvent,
  ConfirmRequestEvent,
  HelloEvent,
  ProtocolErrorEvent,
  StatusFlashEvent,
  StatusUpdateEvent,
} from "../transport/protocol.js";
import type { ThinkFilterState } from "../stream/thinkBlocks.js";
import { initialThinkFilterState } from "../stream/thinkBlocks.js";

/**
 * Bound on `lines` to prevent unbounded growth in long sessions
 * (OOM at ~4 GB heap was observed after a few minutes of OSINT
 * activity). When the array would exceed this, the OLDEST
 * entries are dropped — the user loses early scrollback but
 * keeps the most-recent context. 1000 lines is generous and
 * still well under any plausible memory ceiling.
 */
export const LINES_CAP = 5000;

export interface TranscriptLine {
  /** Stable id for React keys. Monotonic. */
  key: number;
  role:
    | "user" | "assistant" | "system" | "tool" | "separator"
    /** Line inside a ``` fenced code block in assistant text.
     * Renders with a left gutter + code-style color. */
    | "code"
    /** ``@@ ... @@`` diff hunk header. */
    | "diff-hunk"
    /** ``---`` / ``+++`` diff file headers. */
    | "diff-file"
    /** ``+ added line`` in a diff. */
    | "diff-add"
    /** ``- removed line`` in a diff. */
    | "diff-del";
  content: string;
}

export interface ToolLaneEntry {
  /** call_id from the protocol — uniquely identifies the tool call. */
  id: string;
  tool: string;
  /** Compact preview of args, fits on one line. */
  args: string;
  /** ``performance.now()`` at tool.start — drives the elapsed-time
   * counter rendered next to the spinner so the user can see how
   * long a tool call has been pending. */
  startedAtMs: number;
}

export interface TuiState {
  /** Banner event from the gateway. Null until first hello arrives. */
  banner: BannerEvent | null;
  /** Latest status snapshot (model · profile · tokens · elapsed). */
  status: StatusUpdateEvent | null;
  /** Fatal protocol error, surfaced for the user. Null in healthy sessions. */
  protocolError: ProtocolErrorEvent | null;
  /** Server's hello payload. Useful for version-display debugging. */
  serverHello: HelloEvent | null;
  /** Persistent transcript of completed lines. Append-only. */
  lines: TranscriptLine[];
  /** Live streaming assistant text (filtered for display:
   * <think> blocks collapsed to "· thinking…" markers).
   * Built INCREMENTALLY by appending each delta's filter
   * output — no longer rebuilt from a full raw buffer on
   * every delta (which was O(N²) and OOM'd long streams). */
  streaming: string;
  /** Carry state for the incremental <think> filter. Holds
   * `inThink`, a small `tail` for tag boundaries spanning
   * deltas, and the length of the live "thinking…" marker
   * on the streaming buffer so we can swap it for "(thought)"
   * when the block closes. */
  _streamFilter: ThinkFilterState;
  streamId: string | null;
  /** Active tool calls in the bottom-pinned activity lane. */
  toolLane: ToolLaneEntry[];
  /** Currently-displayed ephemeral status flash. Null when none. */
  flash: StatusFlashEvent | null;
  /** Confirmation overlay (Bash/Edit/Write guard). Null when none. */
  confirmReq: ConfirmRequestEvent | null;
  /** AskUserQuestion overlay. Null when no question is pending.
   * Owns the whole keyboard until answered (or Esc cancels). */
  askReq: AskQuestionRequestEvent | null;
  /** Scrollback: how many lines from the bottom we're scrolled up. */
  scrollOffset: number;
  /** Monotonic counter for line keys. */
  _nextKey: number;
  /** ``performance.now()`` of the last progress event (stream delta,
   * tool start/complete, message append). Heartbeat status events
   * do NOT bump this — only events that indicate the agent / model
   * is actually doing work. Used by the stalled-turn detector. */
  _lastProgressMs: number;
  /** ``performance.now()`` when the user pressed enter on a message;
   * null when the agent is idle at the prompt. Cleared as soon as
   * the first stream / tool / message event for the response arrives
   * (we then rely on _lastProgressMs + streamId / toolLane to detect
   * mid-turn stalls). */
  _pendingUserInputSince: number | null;
}

export const initialTuiState: TuiState = {
  banner: null,
  status: null,
  protocolError: null,
  serverHello: null,
  lines: [],
  streaming: "",
  _streamFilter: initialThinkFilterState,
  streamId: null,
  toolLane: [],
  flash: null,
  confirmReq: null,
  askReq: null,
  scrollOffset: 0,
  _nextKey: 1,
  _lastProgressMs: 0,
  _pendingUserInputSince: null,
};
