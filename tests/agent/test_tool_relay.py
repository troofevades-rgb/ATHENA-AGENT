"""gateway_relay tool flag + the tool-result relay sink.

Pins:
  - Tool.gateway_relay defaults False; @tool(gateway_relay=True) forwards
  - skills_list is flagged for relay (the result is the user's answer)
  - the ContextVar sink delivers (name, result) to a bound sink, no-ops
    when unbound, and swallows sink exceptions
"""

from __future__ import annotations

from athena import tools
from athena.agent.tool_relay import (
    emit_tool_result,
    reset_tool_result_sink,
    set_tool_result_sink,
)
from athena.tools.registry import Tool, tool


def test_tool_dataclass_defaults_to_no_relay() -> None:
    t = Tool(
        name="_relay_probe",
        description="probe",
        parameters={"type": "object", "properties": {}},
        func=lambda: "ok",
    )
    assert t.gateway_relay is False


def test_tool_decorator_forwards_gateway_relay() -> None:
    @tool(
        name="_relay_flag_tool",
        description="probe",
        parameters={"type": "object", "properties": {}},
        toolset="_test",
        gateway_relay=True,
    )
    def _impl() -> str:
        return "ok"

    t = tools.get_tool("_relay_flag_tool")
    assert t is not None
    assert t.gateway_relay is True


def test_skills_list_is_relay_flagged() -> None:
    import athena.tools.skill_tools  # noqa: F401 — ensure registered

    t = tools.get_tool("skills_list")
    assert t is not None
    assert t.gateway_relay is True


def test_emit_reaches_bound_sink_then_noops_after_reset() -> None:
    seen: list[tuple[str, str]] = []
    token = set_tool_result_sink(lambda n, r: seen.append((n, r)))
    emit_tool_result("skills_list", "- a\n- b")
    reset_tool_result_sink(token)
    emit_tool_result("skills_list", "dropped")  # no sink bound now
    assert seen == [("skills_list", "- a\n- b")]


def test_emit_is_noop_when_unbound() -> None:
    # Must not raise with nothing bound.
    emit_tool_result("whatever", "x")


def test_emit_swallows_sink_exceptions() -> None:
    def _boom(name: str, result: str) -> None:
        raise RuntimeError("sink blew up")

    token = set_tool_result_sink(_boom)
    try:
        emit_tool_result("x", "y")  # must not propagate
    finally:
        reset_tool_result_sink(token)
