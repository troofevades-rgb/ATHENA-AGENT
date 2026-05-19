"""Smoke test for /dump. Verifies the slash dispatcher renders the system
message via the shared console, without booting the REPL."""

import io
from unittest.mock import MagicMock

from rich.console import Console

from athena import ui
from athena.__main__ import _handle_slash


def _make_fake_agent() -> MagicMock:
    a = MagicMock()
    a.messages = [
        {"role": "system", "content": "SYSTEM-MESSAGE-MARKER lorem ipsum"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    return a


def test_dump_prints_system_prompt(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(ui, "console", Console(file=buf, force_terminal=False, width=200))
    cont = _handle_slash(_make_fake_agent(), "/dump")
    assert cont is True
    output = buf.getvalue()
    assert "SYSTEM-MESSAGE-MARKER" in output
    assert "system prompt:" in output  # the size header


def test_dump_with_no_system_message(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(ui, "console", Console(file=buf, force_terminal=False, width=200))
    a = MagicMock()
    a.messages = [{"role": "user", "content": "hello"}]
    cont = _handle_slash(a, "/dump")
    assert cont is True
    assert "no system message" in buf.getvalue()
