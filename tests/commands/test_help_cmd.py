"""``/help`` renders SLASH_HELP literally without Rich markup parsing.

The previous implementation called ``ui.console.print(SLASH_HELP)``
with markup enabled (Rich's default). Several lines in SLASH_HELP
wrap argument placeholders in square brackets -- ``[file]``,
``[path]``, ``[name]``, ``[ref]``, ``[prompt]``,
``[list|show|delete|dir]``, ``[goal:<id>]`` -- which Rich treats as
markup tags and silently eats. In practice that meant ``/help``
showed ``/save         save transcript`` with the ``[file]`` hint
missing, leaving operators wondering what argument to pass; worse,
malformed-markup parser state can leak into the NEXT console.print
call and crash the next user-visible message.

This test asserts every bracket-wrapped placeholder appears in the
rendered output.
"""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from athena.commands import help as help_cmd


PLACEHOLDERS = (
    "[file]",
    "[path]",
    "[ref]",
    "[name]",
    "[prompt]",
    "[list|show|delete|dir]",
    "[MSG|pause|resume|status|clear]",
    "[goal:<id>]",
)


def _render_with_default_console(monkeypatch: pytest.MonkeyPatch) -> str:
    """Run ``cmd_help`` through a captured Rich Console that mirrors
    ``athena.ui.console``'s defaults (markup-on)."""
    buf = StringIO()
    fake = Console(file=buf, force_terminal=False, no_color=True, width=200)
    monkeypatch.setattr("athena.commands.help.ui.console", fake)

    class _Stub:
        pass

    help_cmd.cmd_help(_Stub(), "")
    return buf.getvalue()


def test_help_renders_bracket_placeholders_literally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every ``[placeholder]`` snippet in SLASH_HELP must survive
    rendering. Rich's markup parser eats them by default; ``cmd_help``
    must opt out so the output is faithful."""
    rendered = _render_with_default_console(monkeypatch)
    missing = [p for p in PLACEHOLDERS if p not in rendered]
    assert not missing, (
        "/help dropped these bracket-wrapped placeholders -- Rich "
        "markup parsing is back on for SLASH_HELP: "
        f"{missing}"
    )


def test_help_returns_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """cmd_help returns "" so the REPL doesn't try to run the rendered
    text as a user turn. Returning a non-empty string would re-enter
    run_turn with the help text as the prompt."""
    buf = StringIO()
    fake = Console(file=buf)
    monkeypatch.setattr("athena.commands.help.ui.console", fake)
    result = help_cmd.cmd_help(object(), "")
    assert result == ""
