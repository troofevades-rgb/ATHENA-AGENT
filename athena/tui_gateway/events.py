"""Event + command dataclasses for the TUI gateway protocol.

The **authoritative** protocol definition lives at
``athena/tui_gateway/schema/v1/protocol.json`` (added in TUI sprint
foundation step 2). The dataclasses in this file mirror those
schemas; the TypeScript interfaces at
``ui-tui/src/transport/protocol.ts`` mirror them too.

Edit the schema first when changing the protocol, then update this
file and the TS file to match. Drift between {schema, Python, TS}
is caught by ``tests/tui_gateway/test_schema_parity.py``.

Wire format is line-delimited JSON-RPC 2.0. Events are JSON-RPC
notifications (no ``id``, ``method`` is the event type); most
commands are notifications too; only ``confirm.reply`` is
correlated by request_id.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# ---- gateway → TUI events ------------------------------------------------


@dataclass(frozen=True)
class _Event:
    """Base for typed events. Subclass and set ``type`` literal."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolSetSummary:
    name: str
    tools: list[str]
    hidden_count: int = 0


@dataclass(frozen=True)
class ThemePalette:
    """Resolved theme colors. Shipped with banner + theme.change
    so the TUI never needs its own theme table."""

    name: str
    description: str
    primary: str
    primary_dim: str
    primary_faint: str
    accent: str
    accent_dim: str
    gradient: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BannerEvent(_Event):
    """Initial render — model, workspace, theme, tool catalog.

    The visual payload ships two ways:

    - ``owl_pixels``: half-block pixel matrix from the source
      photo, used when the TUI can render truecolor (every
      modern terminal can). Gives photo-grade detail.
    - ``owl_art``: ASCII fallback for legacy / no-truecolor
      contexts. Same characters the artist drew.

    The TUI prefers ``owl_pixels`` when present and falls back
    to ``owl_art`` otherwise. ``palette`` is the resolved theme
    so the TUI never needs its own color table.
    """

    model: str
    cwd: str
    theme: str
    tools: list[ToolSetSummary]
    owl_art: list[str] = field(default_factory=list)
    owl_pixels: dict[str, Any] | None = None
    palette: ThemePalette | None = None
    commands_hint: str = ""
    type: Literal["banner"] = "banner"


@dataclass(frozen=True)
class MessageAppendEvent(_Event):
    """Add a full message to the transcript (non-streaming)."""

    role: Literal["user", "assistant", "system", "tool"]
    content: str
    type: Literal["message.append"] = "message.append"


@dataclass(frozen=True)
class StreamStartEvent(_Event):
    """Begin a streaming assistant response."""

    stream_id: str
    role: Literal["assistant"] = "assistant"
    type: Literal["stream.start"] = "stream.start"


@dataclass(frozen=True)
class StreamDeltaEvent(_Event):
    """Append text to an in-flight assistant stream."""

    stream_id: str
    text: str
    type: Literal["stream.delta"] = "stream.delta"


@dataclass(frozen=True)
class StreamEndEvent(_Event):
    """Mark the assistant stream complete.

    ``final_text`` (optional) carries the post-processed view of the
    stream -- ``<think>...</think>`` blocks stripped, any other
    finalize-time cleanup applied. When present, the TUI replaces
    the accumulated stream buffer with ``final_text`` so the
    polished view is what the user sees in the transcript. When
    None (legacy callers, raw-passthrough mode), the TUI keeps
    whatever it accumulated. Streaming chunks are still raw so
    the in-flight typing feel is preserved; only the FINAL frame
    is swapped.
    """

    stream_id: str
    final_text: str | None = None
    type: Literal["stream.end"] = "stream.end"


@dataclass(frozen=True)
class ToolStartEvent(_Event):
    """A tool call is in flight. Renders in the live activity
    lane, NOT the transcript (the Hermes pattern)."""

    call_id: str
    tool: str
    args_preview: str
    type: Literal["tool.start"] = "tool.start"


@dataclass(frozen=True)
class ToolProgressEvent(_Event):
    """Tool emitted a progress note while running."""

    call_id: str
    note: str
    type: Literal["tool.progress"] = "tool.progress"


@dataclass(frozen=True)
class ToolCompleteEvent(_Event):
    """Tool finished; ``ok`` distinguishes success from error."""

    call_id: str
    tool: str
    ok: bool
    result_preview: str
    type: Literal["tool.complete"] = "tool.complete"


@dataclass(frozen=True)
class StatusUpdateEvent(_Event):
    """Periodic status-bar refresh (model, elapsed, tokens)."""

    model: str | None = None
    profile: str | None = None
    elapsed_seconds: float | None = None
    tokens_up: int | None = None
    tokens_down: int | None = None
    tool_summary: str | None = None
    # When True the agent is in plan mode (read-only investigation
    # only). The TUI surfaces this prominently — tinted composer
    # border + banner — so the user can't forget the constraint.
    plan_mode: bool = False
    type: Literal["status"] = "status"


@dataclass(frozen=True)
class StatusFlashEvent(_Event):
    """Ephemeral status message — appears briefly above the
    prompt and decays. NOT persisted in the transcript. Used
    for agent-internal info chatter ("recovered N tool calls",
    "loaded ATHENA.md") that would otherwise interleave with
    streaming assistant text and look buggy."""

    text: str
    level: Literal["info", "warn"] = "info"
    ttl_seconds: float = 3.0
    type: Literal["status.flash"] = "status.flash"


@dataclass(frozen=True)
class ThemeChangeEvent(_Event):
    """User switched themes; TUI repaints with the new palette."""

    theme: str
    palette: ThemePalette
    type: Literal["theme.change"] = "theme.change"


@dataclass(frozen=True)
class ExitEvent(_Event):
    """Tell the TUI to shut down."""

    reason: str = ""
    type: Literal["exit"] = "exit"


@dataclass(frozen=True)
class ConfirmRequestEvent(_Event):
    """Ask the user a yes/no question. The TUI shows a Y/N prompt
    overlay; the user's answer comes back as ``ConfirmReplyCommand``
    with the matching ``request_id``.

    Critical for safety-tier tool approvals (Bash, Edit, Write) —
    without this round-trip, the agent's ``ui.confirm()`` call
    would deadlock waiting on a blocking ``input()`` while Ink
    owns stdin.

    Optional richness fields (added in TUI polish bundle 14):
      ``tool_name`` — the tool that triggered the prompt, used by
        the TUI as a header above the question.
      ``preview`` — multi-line preview body the TUI shows in a
        styled region (command for Bash, diff for Edit, file path +
        first lines for Read on sensitive paths, etc.).
      ``preview_kind`` — selects rendering style for ``preview``:
        ``"command"`` (shell-styled), ``"diff"`` (+/- colored),
        ``"file"`` (path + content), or ``"text"`` (plain).
    """

    request_id: str
    prompt: str
    default: bool = False
    tool_name: str | None = None
    preview: str | None = None
    preview_kind: Literal["command", "diff", "file", "text"] | None = None
    type: Literal["confirm.request"] = "confirm.request"


@dataclass(frozen=True)
class AskQuestionRequestEvent(_Event):
    """Ask the user one or more multiple-choice questions. Mirrors the
    ConfirmRequest round-trip but richer: each question has 2-4
    typed options, optional multiSelect, and an implicit "Other (type
    custom)" choice.

    Critical: without this round-trip, ``AskUserQuestion`` would fall
    back to ``input()`` while Ink owns stdin, which blocks forever
    (the bug that surfaced when a real session hung for 136 minutes
    on a tool the user never saw).

    ``questions`` is a list of dicts shaped like the AskUserQuestion
    tool's input — each entry has ``question``, ``options`` (list of
    {label, description}), and optional ``header`` / ``multiSelect``.
    """

    request_id: str
    questions: list[dict[str, Any]]
    type: Literal["ask_question.request"] = "ask_question.request"


@dataclass(frozen=True)
class HelloEvent(_Event):
    """First frame from the gateway after a client connects.

    Declares the wire protocol version, the athena version, and a
    list of capability strings (e.g. ``"heartbeats"``, ``"replay"``).
    Client compares ``protocol_version`` and decides whether to
    proceed. ``current_seq`` is the highest event seq the gateway
    has emitted so far (0 on a fresh gateway).
    """

    protocol_version: int
    athena_version: str
    capabilities: list[str]
    current_seq: int = 0
    type: Literal["hello"] = "hello"


@dataclass(frozen=True)
class PingEvent(_Event):
    """Gateway → TUI keepalive. Emitted every ~5s. Client must reply
    with a :class:`PongCommand`. Three missed pongs in a row indicate
    a dead TUI."""

    type: Literal["ping"] = "ping"


@dataclass(frozen=True)
class ProtocolErrorEvent(_Event):
    """Fatal protocol error. Gateway emits this once before closing,
    so the client can render a clear message instead of seeing an
    opaque socket-closed.

    Defined codes: ``protocol_version_mismatch``, ``tui_heartbeat_lost``,
    ``malformed_hello``.
    """

    code: str
    message: str
    type: Literal["protocol.error"] = "protocol.error"


Event = (
    HelloEvent
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
    | AskQuestionRequestEvent
)


# ---- TUI → gateway commands ---------------------------------------------


@dataclass(frozen=True)
class UserInputCommand:
    """User typed a line and hit enter."""

    text: str
    type: Literal["user.input"] = "user.input"


@dataclass(frozen=True)
class InterruptCommand:
    """User hit Ctrl-C — abort the current operation."""

    type: Literal["interrupt"] = "interrupt"


@dataclass(frozen=True)
class SlashCommand:
    """``/<command> <arg>``. Parsed TUI-side, dispatched here."""

    command: str
    arg: str
    type: Literal["slash"] = "slash"


@dataclass(frozen=True)
class ResizeCommand:
    """Terminal size changed; the agent may want to re-render."""

    cols: int
    rows: int
    type: Literal["resize"] = "resize"


@dataclass(frozen=True)
class ConfirmReplyCommand:
    """User's yes/no answer to a prior ``ConfirmRequestEvent``.
    Correlated by ``request_id``."""

    request_id: str
    accepted: bool
    type: Literal["confirm.reply"] = "confirm.reply"


@dataclass(frozen=True)
class AskQuestionReplyCommand:
    """User's answer(s) to a prior ``AskQuestionRequestEvent``.

    ``answers`` is a list (parallel to the questions list in the
    request) of ``{question, answer}`` dicts. ``answer`` is a string
    (single-select: the picked option's label, or custom text for
    "Other"; multi-select: comma-joined labels).

    ``cancelled`` set to True means the user dismissed without
    answering (Esc) — the agent gets a sentinel rather than guessing
    a default.
    """

    request_id: str
    answers: list[dict[str, str]]
    cancelled: bool = False
    type: Literal["ask_question.reply"] = "ask_question.reply"


@dataclass(frozen=True)
class HelloCommand:
    """First frame from the TUI in response to the gateway's hello.

    ``last_seq`` is the highest event seq the client has already
    seen; the gateway uses it to replay missed events from its
    ring buffer on reconnect. 0 on a fresh start (no events to
    replay).
    """

    protocol_version: int
    client_version: str
    capabilities: list[str]
    last_seq: int = 0
    type: Literal["hello"] = "hello"


@dataclass(frozen=True)
class PongCommand:
    """TUI → gateway keepalive reply to a :class:`PingEvent`."""

    type: Literal["pong"] = "pong"


Command = (
    HelloCommand
    | PongCommand
    | UserInputCommand
    | InterruptCommand
    | SlashCommand
    | ResizeCommand
    | ConfirmReplyCommand
    | AskQuestionReplyCommand
)


def command_from_json_rpc(method: str, params: dict[str, Any]) -> Command | None:
    """Decode a JSON-RPC method+params into a typed command.
    Returns None for unrecognized methods so the server can emit
    METHOD_NOT_FOUND without raising."""
    if method == "hello":
        return HelloCommand(
            protocol_version=int(params.get("protocol_version", 0)),
            client_version=str(params.get("client_version", "")),
            capabilities=list(params.get("capabilities", []) or []),
            last_seq=int(params.get("last_seq", 0)),
        )
    if method == "pong":
        return PongCommand()
    if method == "user.input":
        return UserInputCommand(text=str(params.get("text", "")))
    if method == "interrupt":
        return InterruptCommand()
    if method == "slash":
        return SlashCommand(
            command=str(params.get("command", "")),
            arg=str(params.get("arg", "")),
        )
    if method == "resize":
        return ResizeCommand(
            cols=int(params.get("cols", 0)),
            rows=int(params.get("rows", 0)),
        )
    if method == "confirm.reply":
        return ConfirmReplyCommand(
            request_id=str(params.get("request_id", "")),
            accepted=bool(params.get("accepted", False)),
        )
    if method == "ask_question.reply":
        answers_raw = params.get("answers") or []
        # Coerce each entry to {question: str, answer: str} so the
        # tool gets a stable shape regardless of TUI-side glitches.
        answers = [
            {
                "question": str(a.get("question", "")),
                "answer": str(a.get("answer", "")),
            }
            for a in answers_raw
            if isinstance(a, dict)
        ]
        return AskQuestionReplyCommand(
            request_id=str(params.get("request_id", "")),
            answers=answers,
            cancelled=bool(params.get("cancelled", False)),
        )
    return None
