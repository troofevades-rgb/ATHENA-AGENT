"""Tests for ``/plan`` and ``/plan-exit`` — toggle plan mode."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from athena.commands.plan_command import cmd_plan, cmd_plan_exit


def _capture():
    lines: list[str] = []
    patches = []
    for fn in ("info", "warn", "error"):
        patches.append(
            patch(
                f"athena.commands.plan_command.ui.{fn}",
                side_effect=lambda msg, *a, _n=fn, **kw:
                    lines.append(f"{_n}: {msg}"),
            )
        )
    return lines, patches


def _run(cmd_fn, arg: str) -> tuple[str, str]:
    """Run ``cmd_fn(agent, arg)`` and return (ui_capture, return_value)."""
    lines, patches = _capture()
    for p in patches:
        p.start()
    try:
        result = cmd_fn(SimpleNamespace(), arg)
    finally:
        for p in patches:
            p.stop()
    return "\n".join(lines), result


# ---- /plan ----------------------------------------------------------


def test_plan_no_arg_enters_mode_and_returns_empty() -> None:
    """Bare ``/plan`` enters plan mode and returns "" so the REPL
    doesn't send anything to the model."""
    enter_calls: list[None] = []
    with patch(
        "athena.commands.plan_command.plan_mod.enter_plan_mode",
        side_effect=lambda: enter_calls.append(None),
    ):
        out, ret = _run(cmd_plan, "")
    assert enter_calls == [None]
    assert ret == ""
    assert "plan mode" in out.lower()
    assert "/plan-exit" in out  # tell user how to leave


def test_plan_with_prompt_returns_drafting_prompt() -> None:
    """``/plan <prompt>`` enters plan mode AND returns a synthetic
    user message asking the model to draft a plan for the prompt."""
    enter_calls: list[None] = []
    with patch(
        "athena.commands.plan_command.plan_mod.enter_plan_mode",
        side_effect=lambda: enter_calls.append(None),
    ):
        out, ret = _run(cmd_plan, "refactor the auth layer")
    assert enter_calls == [None]
    # Return value seeds a turn — must mention the user's request.
    assert "refactor the auth layer" in ret
    assert "plan" in ret.lower()
    assert "ExitPlanMode" in ret  # tells the model how to leave
    assert "refactor the auth layer" in out  # also echoed via info


def test_plan_strips_whitespace_from_arg() -> None:
    enter_calls: list[None] = []
    with patch(
        "athena.commands.plan_command.plan_mod.enter_plan_mode",
        side_effect=lambda: enter_calls.append(None),
    ):
        _, ret = _run(cmd_plan, "   leading and trailing   ")
    assert "leading and trailing" in ret
    assert ret.count("   leading") == 0  # whitespace stripped


# ---- /plan-exit -----------------------------------------------------


def test_plan_exit_calls_exit_silent_and_returns_empty() -> None:
    exit_calls: list[None] = []
    with patch(
        "athena.commands.plan_command.plan_mod.exit_plan_mode_silent",
        side_effect=lambda: exit_calls.append(None),
    ):
        out, ret = _run(cmd_plan_exit, "")
    assert exit_calls == [None]
    assert ret == ""
    assert "exited" in out.lower()


def test_plan_exit_ignores_arg() -> None:
    """Slash arg is meaningless for /plan-exit; passing junk must
    not break it."""
    exit_calls: list[None] = []
    with patch(
        "athena.commands.plan_command.plan_mod.exit_plan_mode_silent",
        side_effect=lambda: exit_calls.append(None),
    ):
        _, ret = _run(cmd_plan_exit, "ignored garbage")
    assert exit_calls == [None]
    assert ret == ""
