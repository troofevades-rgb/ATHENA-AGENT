"""Round-trip tests for the JSON-RPC protocol.

These tests verify the Python side of the protocol in isolation —
event serialization, command decoding, error edge cases. The
TS-side mirror is covered by Bun tests under ``ui-tui/``.

End-to-end gateway↔bundle tests live in ``test_subprocess.py``
because they need Node + the built JS bundle, which a unit-test
run shouldn't require.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from athena.tui_gateway.events import (
    BannerEvent,
    InterruptCommand,
    MessageAppendEvent,
    ResizeCommand,
    SlashCommand,
    StreamDeltaEvent,
    StreamEndEvent,
    StreamStartEvent,
    ThemeChangeEvent,
    ThemePalette,
    ToolCompleteEvent,
    ToolSetSummary,
    ToolStartEvent,
    UserInputCommand,
    command_from_json_rpc,
)


def test_banner_event_serializes_with_type_field():
    evt = BannerEvent(
        model="x",
        cwd="/tmp/ws",
        theme="cyber",
        tools=[
            ToolSetSummary(name="file", tools=["Read", "Edit"]),
            ToolSetSummary(name="shell", tools=["Bash"], hidden_count=2),
        ],
    )
    d = asdict(evt)
    assert d["type"] == "banner"
    assert d["model"] == "x"
    # Nested dataclasses are flattened to dicts by ``asdict``,
    # which is exactly what the JSON-RPC frame needs.
    assert d["tools"][1]["hidden_count"] == 2


def test_stream_lifecycle_events_share_stream_id():
    """The TUI uses stream_id to correlate start/delta/end."""
    sid = "stream-123"
    start = StreamStartEvent(stream_id=sid)
    delta = StreamDeltaEvent(stream_id=sid, text="hi")
    end = StreamEndEvent(stream_id=sid)
    assert start.stream_id == delta.stream_id == end.stream_id


def test_tool_complete_carries_ok_flag():
    """ok=False signals an error path so the TUI can render
    the activity-lane entry red instead of green."""
    ok = ToolCompleteEvent(
        call_id="c1", tool="Read", ok=True, result_preview="42 lines"
    )
    err = ToolCompleteEvent(
        call_id="c2", tool="Bash", ok=False, result_preview="exit 1"
    )
    assert ok.ok and not err.ok


def test_user_input_decodes_from_dict():
    cmd = command_from_json_rpc("user.input", {"text": "hello"})
    assert isinstance(cmd, UserInputCommand)
    assert cmd.text == "hello"


def test_interrupt_decodes_with_empty_params():
    cmd = command_from_json_rpc("interrupt", {})
    assert isinstance(cmd, InterruptCommand)


def test_slash_decodes_command_and_arg():
    cmd = command_from_json_rpc(
        "slash", {"command": "theme", "arg": "set cyber"}
    )
    assert isinstance(cmd, SlashCommand)
    assert cmd.command == "theme"
    assert cmd.arg == "set cyber"


def test_resize_coerces_ints():
    """The TS side sends numbers; defensive coercion lets us
    accept stringified ints without crashing."""
    cmd = command_from_json_rpc("resize", {"cols": "120", "rows": 40})
    assert isinstance(cmd, ResizeCommand)
    assert cmd.cols == 120
    assert cmd.rows == 40


def test_unknown_method_returns_none():
    """Server uses None to signal 'reply METHOD_NOT_FOUND if this
    was a request' — Python decoder must not raise on garbage."""
    assert command_from_json_rpc("garbage.method", {}) is None
    assert command_from_json_rpc("", {}) is None


def test_message_append_uses_dotted_type():
    """``type`` literals match the TS protocol verbatim. A typo
    here is silent until the TUI ignores the event."""
    evt = MessageAppendEvent(role="user", content="hi")
    assert asdict(evt)["type"] == "message.append"


def test_theme_change_carries_full_palette():
    """Theme.change ships the resolved palette so the TUI doesn't
    need its own theme table — single source of truth in Python."""
    palette = ThemePalette(
        name="cyber",
        description="neon",
        primary="#00ff9f",
        primary_dim="#00aa6b",
        primary_faint="#004433",
        accent="#ff00aa",
        accent_dim="#aa0070",
        gradient=["#a", "#b", "#c"],
    )
    evt = ThemeChangeEvent(theme="cyber", palette=palette)
    d = asdict(evt)
    assert d["palette"]["primary"] == "#00ff9f"
    assert d["palette"]["gradient"] == ["#a", "#b", "#c"]


def test_event_round_trips_through_json():
    """Wire format: JSON-RPC notification. Server strips ``type``
    from params (it's redundant with ``method``). Re-attach
    on decode."""
    evt = ToolStartEvent(
        call_id="c1", tool="Read", args_preview="file=foo.py"
    )
    params = {k: v for k, v in asdict(evt).items() if k != "type"}
    frame = {
        "jsonrpc": "2.0",
        "method": evt.type,
        "params": params,
    }
    line = json.dumps(frame)
    decoded = json.loads(line)
    assert decoded["method"] == "tool.start"
    assert decoded["params"]["tool"] == "Read"
