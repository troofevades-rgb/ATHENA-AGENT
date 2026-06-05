"""Background-fork output must not leak into the foreground TUI.

Regression: once the live tool-call / stream emitters started shipping
``send_event`` straight to the process-global ``_active_gateway`` (the
TUI gateway path, added in the TUI overhaul), the 7-day curator pass and
the per-turn review fork began rendering their own tool calls into the
user's foreground transcript. Typing "hello" looked like it triggered a
``skill_view`` spree because the concurrently-firing curator's
"inspect each skill" prompt was bleeding through.

The ``console.print`` bridge was always fork-safe (its ``_bridge_context``
ContextVar defaults to False and doesn't propagate to the fork's thread).
These tests pin the same guarantee for the explicit ``send_event`` path:
emits under a background write origin (curator / background_review) reach
no gateway, while foreground emits still do.
"""

from __future__ import annotations

from athena import ui
from athena.provenance import (
    BACKGROUND_REVIEW,
    CURATOR,
    FOREGROUND,
    SUBAGENT,
    get_current_write_origin,
    reset_current_write_origin,
    set_current_write_origin,
)

from ._helpers import FakeTuiGateway


def test_foreground_tool_result_reaches_gateway() -> None:
    gw = FakeTuiGateway()
    ui.set_gateway(gw)
    try:
        # Default origin is FOREGROUND; no override needed.
        ui.tool_result("skill_view", "body of a skill", duration_s=0.01)
    finally:
        ui.set_gateway(None)

    assert gw.events_of_type("tool.complete"), "foreground emit should reach the TUI"


def test_subagent_tool_calls_surface_nested() -> None:
    """The user-invoked sub-agent (Agent tool) is NOT silent like the
    background passes: its tool calls reach the TUI, flagged ``nested``
    so the reducer renders them dimmed under the sub-agent."""
    gw = FakeTuiGateway()
    ui.set_gateway(gw)
    token = set_current_write_origin(SUBAGENT)
    try:
        ui.tool_call_summary("Grep", {"pattern": "callers"}, call_id="Grep#1")
        ui.tool_result("Grep", "4 hits", duration_s=0.01, call_id="Grep#1")
    finally:
        reset_current_write_origin(token)
        ui.set_gateway(None)

    starts = gw.events_of_type("tool.start")
    completes = gw.events_of_type("tool.complete")
    assert starts and completes, "sub-agent tool calls should reach the TUI"
    assert completes[0].nested is True, "sub-agent tool.complete must be flagged nested"


def test_subagent_prose_is_suppressed() -> None:
    """Only the sub-agent's TOOL activity surfaces — its streaming prose
    / info chatter (kind='all') stays suppressed so the parent transcript
    isn't flooded."""
    gw = FakeTuiGateway()
    ui.set_gateway(gw)
    token = set_current_write_origin(SUBAGENT)
    try:
        assert ui._emit_gateway("tool") is gw  # tool activity allowed
        assert ui._emit_gateway("all") is None  # prose / info suppressed
        ui.tool_round_header()  # separator uses kind='all' → suppressed
    finally:
        reset_current_write_origin(token)
        ui.set_gateway(None)

    assert gw.events_of_type("message.append") == []
    assert gw.events_of_type("separator") == []


def test_foreground_tool_result_not_flagged_nested() -> None:
    gw = FakeTuiGateway()
    ui.set_gateway(gw)
    try:
        ui.tool_result("Read", "x", duration_s=0.01)
    finally:
        ui.set_gateway(None)
    complete = gw.events_of_type("tool.complete")[0]
    assert complete.nested is False
    assert get_current_write_origin() == FOREGROUND


def test_curator_fork_tool_result_is_suppressed() -> None:
    gw = FakeTuiGateway()
    ui.set_gateway(gw)
    token = set_current_write_origin(CURATOR)
    try:
        ui.tool_result("skill_view", "body of a skill", duration_s=0.01)
        ui.tool_call_summary("skill_view", {"name": "debugging"})
        ui.tool_round_header()
    finally:
        reset_current_write_origin(token)
        ui.set_gateway(None)

    assert gw.events == [], f"curator fork output leaked into the TUI: {gw.event_types()}"


def test_background_review_fork_is_suppressed() -> None:
    gw = FakeTuiGateway()
    ui.set_gateway(gw)
    token = set_current_write_origin(BACKGROUND_REVIEW)
    try:
        ui.tool_result("search_sessions", "some hits", duration_s=0.01)
    finally:
        reset_current_write_origin(token)
        ui.set_gateway(None)

    assert gw.events == [], "background-review fork output leaked into the TUI"


def test_origin_restored_to_foreground_still_emits() -> None:
    """Suppression is scoped to the fork, not sticky on the gateway:
    once the origin is back to foreground, emits flow again."""
    gw = FakeTuiGateway()
    ui.set_gateway(gw)
    token = set_current_write_origin(CURATOR)
    try:
        ui.tool_result("skill_view", "suppressed", duration_s=0.01)
    finally:
        reset_current_write_origin(token)

    assert gw.events == []

    try:
        assert get_current_write_origin() == FOREGROUND
        ui.tool_result("skill_view", "now visible", duration_s=0.01)
    finally:
        ui.set_gateway(None)

    assert gw.events_of_type("tool.complete"), "foreground emit after fork should reach the TUI"
