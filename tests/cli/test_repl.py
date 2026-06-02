"""Public-surface tests for athena/cli/repl.py.

The module was extracted from athena/__main__.py in the 2026-06-01
consolidation pass. This file pins:

  1. The new public names (``handle_slash``, ``run_interactive_repl``)
     are importable from ``athena.cli.repl``.
  2. The backwards-compatible aliases (``_handle_slash``,
     ``_run_interactive_repl``) still importable from
     ``athena.__main__`` for one release.
  3. ``handle_slash`` dispatch behavior: exit verbs return False,
     unknown commands surface a friendly error, known commands
     invoke their registered handler, and a returned prompt
     string runs as a follow-up user turn.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


def test_public_surface_importable() -> None:
    """Module exposes the new canonical names at the top level."""
    from athena.cli.repl import handle_slash, run_interactive_repl

    assert callable(handle_slash)
    assert callable(run_interactive_repl)


def test_backwards_compat_private_names_still_work() -> None:
    """The legacy private names remain importable from athena.__main__
    so existing callers (e.g. athena/commands/loop.py before the
    Refactor 2 follow-up lands) don't break."""
    from athena.__main__ import _handle_slash, _run_interactive_repl

    assert callable(_handle_slash)
    assert callable(_run_interactive_repl)


def test_aliases_point_at_same_objects() -> None:
    """The private-name re-exports and the new public names refer
    to the exact same function objects. Tests that monkeypatch
    one path see the change on the other path too."""
    from athena.__main__ import _handle_slash as legacy_handle
    from athena.__main__ import _run_interactive_repl as legacy_repl
    from athena.cli.repl import handle_slash, run_interactive_repl

    assert legacy_handle is handle_slash
    assert legacy_repl is run_interactive_repl


# ---- handle_slash dispatch ------------------------------------------


def _agent_stub() -> SimpleNamespace:
    """Minimal agent surface for handle_slash."""
    return SimpleNamespace(run_turn=lambda _x: None)


def test_handle_slash_empty_command_returns_true() -> None:
    """A bare ``/`` (no command word) is a no-op that keeps the
    REPL alive."""
    from athena.cli.repl import handle_slash

    assert handle_slash(_agent_stub(), "/") is True


def test_handle_slash_exit_verbs_return_false() -> None:
    """``/exit /quit /q`` are inline-handled (not dispatched through
    the registry) and break the outer REPL loop. Case-insensitive."""
    from athena.cli.repl import handle_slash

    for verb in ("/exit", "/quit", "/q", "/EXIT", "/Quit", "/Q"):
        assert handle_slash(_agent_stub(), verb) is False


def test_handle_slash_unknown_command_surfaces_error() -> None:
    """An unrecognised command logs to ui.error but keeps the loop
    alive (returns True). The /help hint is part of the message
    so the operator sees the discovery path."""
    from athena.cli import repl as repl_mod

    captured: list[str] = []
    with patch.object(repl_mod.ui, "error", side_effect=captured.append):
        result = repl_mod.handle_slash(_agent_stub(), "/blargh")
    assert result is True
    assert any("unknown command" in m.lower() for m in captured)
    assert any("/help" in m.lower() for m in captured)


def test_handle_slash_dispatches_known_command() -> None:
    """A known command is looked up via commands.get_command and
    invoked with (agent, arg)."""
    from athena.cli import repl as repl_mod

    invoked: list[tuple] = []

    def fake_cmd(agent, arg):
        invoked.append((agent, arg))
        return ""

    with patch.object(repl_mod.commands, "get_command", return_value=fake_cmd):
        agent = _agent_stub()
        result = repl_mod.handle_slash(agent, "/help some args")
    assert result is True
    assert invoked == [(agent, "some args")]


def test_handle_slash_runs_turn_when_command_returns_prompt() -> None:
    """If the command handler returns a non-empty string, it's
    treated as a follow-up user prompt that runs as a turn. This
    is the path /goal MSG uses to auto-bootstrap the loop."""
    from athena.cli import repl as repl_mod

    turn_runs: list[str] = []

    def fake_cmd(agent, arg):
        return "synthetic continuation prompt"

    agent = SimpleNamespace(run_turn=turn_runs.append)
    with patch.object(repl_mod.commands, "get_command", return_value=fake_cmd):
        repl_mod.handle_slash(agent, "/goal say hi")
    assert turn_runs == ["synthetic continuation prompt"]


def test_handle_slash_empty_return_does_not_run_turn() -> None:
    """A command that returns "" (the common case) must NOT trigger
    a follow-up turn. Otherwise every /status / /cost / etc would
    spuriously invoke the model."""
    from athena.cli import repl as repl_mod

    turn_runs: list[str] = []

    def fake_cmd(agent, arg):
        return ""

    agent = SimpleNamespace(run_turn=turn_runs.append)
    with patch.object(repl_mod.commands, "get_command", return_value=fake_cmd):
        repl_mod.handle_slash(agent, "/status")
    assert turn_runs == []


def test_handle_slash_keyboard_interrupt_in_followup_turn_is_caught() -> None:
    """If the user Ctrl+Cs the follow-up turn, the REPL loop must
    not die -- it should warn and return True so the prompt comes
    back."""
    from athena.cli import repl as repl_mod

    def fake_cmd(agent, arg):
        return "go"

    def interrupting_run_turn(_x):
        raise KeyboardInterrupt()

    agent = SimpleNamespace(run_turn=interrupting_run_turn)
    warnings: list[str] = []
    with (
        patch.object(repl_mod.commands, "get_command", return_value=fake_cmd),
        patch.object(repl_mod.ui, "warn", side_effect=warnings.append),
    ):
        result = repl_mod.handle_slash(agent, "/goal x")
    assert result is True
    assert any("interrupt" in w.lower() for w in warnings)
