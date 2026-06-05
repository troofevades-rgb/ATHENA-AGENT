/**
 * Event + command interfaces for the TUI gateway protocol.
 *
 * The **authoritative** protocol definition lives at
 * `athena/tui_gateway/schema/v1/protocol.json` (added in TUI sprint
 * foundation step 2). The interfaces in this file mirror those
 * schemas; the Python dataclasses in
 * `athena/tui_gateway/events.py` mirror them too.
 *
 * Edit the schema first when changing the protocol, then update
 * this file and the Python file to match. Drift between
 * {schema, Python, TS} is caught by
 * `tests/tui_gateway/test_schema_parity.py`.
 *
 * Wire format is line-delimited JSON-RPC 2.0. Events flow
 * gateway → tui as notifications; most commands flow tui → gateway
 * as notifications too. Only `confirm.reply` is correlated by
 * `request_id`.
 */

// ----- JSON-RPC envelope -----

export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id?: string | number | null;
  method: string;
  params?: unknown;
}

export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: string | number | null;
  result?: unknown;
  error?: JsonRpcError;
}

export interface JsonRpcError {
  code: number;
  message: string;
  data?: unknown;
}

// ----- Gateway → TUI events (notifications) -----

export type Event =
  | HelloEvent
  | PingEvent
  | ProtocolErrorEvent
  | BannerEvent
  | MessageAppendEvent
  | StreamStartEvent
  | StreamDeltaEvent
  | StreamEndEvent
  | ToolStartEvent
  | ToolProgressEvent
  | ToolCompleteEvent
  | StatusUpdateEvent
  | StatusFlashEvent
  | ThemeChangeEvent
  | ExitEvent
  | ConfirmRequestEvent
  | AskQuestionRequestEvent;

export interface HelloEvent {
  type: "hello";
  protocol_version: number;
  athena_version: string;
  capabilities: string[];
  /** Highest event seq the gateway has emitted so far. 0 on
   * a fresh gateway. Used by clients implementing replay. */
  current_seq?: number;
}

export interface PingEvent {
  type: "ping";
}

export interface ProtocolErrorEvent {
  type: "protocol.error";
  /** One of: "protocol_version_mismatch", "tui_heartbeat_lost",
   * "malformed_hello". */
  code: string;
  message: string;
}

export interface OwlPixelMatrix {
  /** Cells per row (= terminal columns the owl occupies). */
  width: number;
  /** Rows (= terminal rows the owl occupies). Each cell encodes
   * a 2×2 source-pixel region via Unicode quadrant block
   * characters. */
  height: number;
  /**
   * Row-major matrix of ``[glyph, fgHex, bgHex]`` per cell.
   * The glyph is one of the 16 Unicode quadrant block
   * characters (or a space / full block for fully-blank or
   * fully-filled regions); fg/bg are ``#RRGGBB`` truecolor
   * strings the Ink Text component accepts directly.
   */
  cells: string[][][];
}

export interface BannerEvent {
  type: "banner";
  model: string;
  cwd: string;
  theme: string;
  tools: ToolSetSummary[];
  /**
   * Owl ASCII art as raw rows. Fallback path for terminals that
   * can't render truecolor; the TUI prefers ``owl_pixels`` when
   * present.
   */
  owl_art: string[];
  /**
   * Photo-grade pixel matrix from the bundled owl image. Null
   * when Pillow isn't available or the image is missing — TUI
   * falls back to the ASCII art.
   */
  owl_pixels: OwlPixelMatrix | null;
  /** Theme palette resolved on the gateway side. */
  palette: ThemePalette;
  /** Optional commands hint line, e.g. "/help · /theme · /exit". */
  commands_hint: string;
}

export interface ToolSetSummary {
  name: string;
  tools: string[];
  hidden_count?: number;
}

export interface MessageAppendEvent {
  type: "message.append";
  role: "user" | "assistant" | "system" | "tool";
  content: string;
}

export interface StreamStartEvent {
  type: "stream.start";
  stream_id: string;
  role: "assistant";
}

export interface StreamDeltaEvent {
  type: "stream.delta";
  stream_id: string;
  text: string;
}

export interface StreamEndEvent {
  type: "stream.end";
  stream_id: string;
  // Optional polished view of the stream -- <think>...</think>
  // blocks stripped, any other finalize-time cleanup applied.
  // When present, the reducer swaps the accumulated buffer for
  // this string so the transcript shows the clean version.
  // When absent (legacy producer), the buffer is kept as-is.
  final_text?: string;
  // Optional reasoning extracted from the <think> blocks that
  // final_text stripped. Rendered inline only while the reader has
  // "show reasoning" toggled on (Ctrl+O); otherwise held collapsed.
  thinking?: string | null;
}

export interface ToolStartEvent {
  type: "tool.start";
  call_id: string;
  tool: string;
  args_preview: string;
}

export interface ToolProgressEvent {
  type: "tool.progress";
  call_id: string;
  note: string;
}

export interface ToolCompleteEvent {
  type: "tool.complete";
  call_id: string;
  tool: string;
  ok: boolean;
  result_preview: string;
  /** Wall-clock dispatch time in ms; absent on older/non-runtime emitters. */
  duration_ms?: number;
}

export interface StatusUpdateEvent {
  type: "status";
  model?: string;
  profile?: string;
  elapsed_seconds?: number;
  tokens_up?: number;
  tokens_down?: number;
  tool_summary?: string;
  /** Estimated tokens currently occupying the context window. */
  context_used?: number;
  /** Model context window size in tokens. */
  context_limit?: number;
  /** Watermark (0..1) at which the agent auto-compacts the context. */
  context_compact_ratio?: number;
  /** True when the agent is in plan mode (read-only investigation
   * only). TUI surfaces this prominently so the user can't forget
   * the constraint. */
  plan_mode?: boolean;
}

export interface StatusFlashEvent {
  type: "status.flash";
  text: string;
  level: "info" | "warn";
  ttl_seconds: number;
}

export interface ThemeChangeEvent {
  type: "theme.change";
  theme: string;
  palette: ThemePalette;
}

export interface ThemePalette {
  name: string;
  description: string;
  primary: string;
  primary_dim: string;
  primary_faint: string;
  accent: string;
  accent_dim: string;
  gradient: string[];
}

export interface ExitEvent {
  type: "exit";
  reason?: string;
}

export interface ConfirmRequestEvent {
  type: "confirm.request";
  request_id: string;
  prompt: string;
  default: boolean;
  /** Tool name that triggered the prompt — shown as a header. */
  tool_name?: string | null;
  /** Multi-line preview of what's about to happen (Bash command,
   * Edit diff, Write file content, etc.). */
  preview?: string | null;
  /** Rendering style for the preview. */
  preview_kind?: "command" | "diff" | "file" | "text" | null;
}

/** One option in an AskQuestionRequest. */
export interface AskQuestionOption {
  label: string;
  description: string;
}

/** One question in an AskQuestionRequest. */
export interface AskQuestionEntry {
  question: string;
  header?: string;
  multiSelect?: boolean;
  options: AskQuestionOption[];
}

export interface AskQuestionRequestEvent {
  type: "ask_question.request";
  request_id: string;
  questions: AskQuestionEntry[];
}

// ----- TUI → Gateway commands -----

export interface ConfirmReplyCommand {
  type: "confirm.reply";
  request_id: string;
  accepted: boolean;
}

export interface AskQuestionReplyCommand {
  type: "ask_question.reply";
  request_id: string;
  /** Parallel to the request's questions list. */
  answers: { question: string; answer: string }[];
  /** True when the user dismissed without answering (Esc). */
  cancelled?: boolean;
}

export type Command =
  | HelloCommand
  | PongCommand
  | UserInputCommand
  | InterruptCommand
  | SlashCommand
  | ResizeCommand
  | ConfirmReplyCommand
  | AskQuestionReplyCommand;

export interface HelloCommand {
  type: "hello";
  protocol_version: number;
  client_version: string;
  capabilities: string[];
  /** Highest seq the client has already seen. 0 on a fresh
   * start. Gateway replays events > last_seq from its ring
   * buffer when present. */
  last_seq?: number;
}

export interface PongCommand {
  type: "pong";
}

export interface UserInputCommand {
  type: "user.input";
  text: string;
}

export interface InterruptCommand {
  type: "interrupt";
}

export interface SlashCommand {
  type: "slash";
  command: string;
  arg: string;
}

export interface ResizeCommand {
  type: "resize";
  cols: number;
  rows: number;
}

// JSON-RPC method names — gateway exposes these as RPC handlers.
export const METHODS = {
  HELLO: "hello",
  PONG: "pong",
  USER_INPUT: "user.input",
  INTERRUPT: "interrupt",
  SLASH: "slash",
  RESIZE: "resize",
} as const;

// Standard JSON-RPC error codes we use.
export const ERRORS = {
  PARSE_ERROR: -32700,
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INVALID_PARAMS: -32602,
  INTERNAL_ERROR: -32603,
} as const;
