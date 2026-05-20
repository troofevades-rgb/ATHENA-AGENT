"""Tests for athena.tools.clarify (T2-08.2).

Sync tests — matches the actual tool surface; the spec's
@pytest.mark.asyncio doesn't apply to athena's sync tools.
"""

from __future__ import annotations

import io
import threading
import time
from typing import Any

import pytest

from athena.tools.clarify import (
    GatewayClarifyHook,
    _resolve_line,
    clarify,
    clear_gateway_hook,
    in_fork_context,
    register_gateway_hook,
)


@pytest.fixture(autouse=True)
def _isolate_clarify_state() -> Any:
    """Clear gateway hook + fork context before AND after each test
    so global state can't leak between tests."""
    clear_gateway_hook()
    in_fork_context.set(False)
    yield
    clear_gateway_hook()
    in_fork_context.set(False)


# ---------------------------------------------------------------------------
# Fork auto-deny
# ---------------------------------------------------------------------------


def test_fork_context_returns_auto_deny() -> None:
    in_fork_context.set(True)
    result = clarify(question="which mode?", options=["A", "B"])
    assert "background fork" in result.lower()


def test_fork_context_skips_gateway_hook() -> None:
    """Even when a gateway hook is registered, fork mode wins."""

    class _ShouldNotFire(GatewayClarifyHook):
        def resolve(self, question, options, timeout_seconds, allow_freeform):
            raise AssertionError("gateway hook ran in fork context")

    register_gateway_hook(_ShouldNotFire())
    in_fork_context.set(True)
    result = clarify(question="?", options=["A", "B"])
    assert "background fork" in result.lower()


# ---------------------------------------------------------------------------
# Gateway hook
# ---------------------------------------------------------------------------


def test_gateway_hook_resolves() -> None:
    class _StubHook(GatewayClarifyHook):
        def resolve(self, question, options, timeout_seconds, allow_freeform):
            return options[1]

    register_gateway_hook(_StubHook())
    result = clarify(question="which?", options=["A", "B"])
    assert result == "B"


def test_gateway_hook_returning_none_falls_through_to_stdin(monkeypatch) -> None:
    class _NoOpHook(GatewayClarifyHook):
        def resolve(self, question, options, timeout_seconds, allow_freeform):
            return None

    register_gateway_hook(_NoOpHook())
    monkeypatch.setattr("builtins.input", lambda _prompt: "1")
    result = clarify(question="?", options=["A", "B"], timeout_seconds=5)
    assert result == "A"


def test_gateway_hook_exception_falls_through_to_stdin(monkeypatch) -> None:
    """A misbehaving gateway hook doesn't kill the call — fall through
    to stdin instead."""

    class _RaisingHook(GatewayClarifyHook):
        def resolve(self, question, options, timeout_seconds, allow_freeform):
            raise RuntimeError("hook broke")

    register_gateway_hook(_RaisingHook())
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")
    result = clarify(question="?", options=["A", "B"], timeout_seconds=5)
    assert result == "B"


def test_gateway_hook_passes_arguments_through() -> None:
    """The hook receives the question, options, timeout, and freeform
    flag verbatim."""
    seen: dict[str, Any] = {}

    class _CaptureHook(GatewayClarifyHook):
        def resolve(self, question, options, timeout_seconds, allow_freeform):
            seen["q"] = question
            seen["opts"] = list(options)
            seen["timeout"] = timeout_seconds
            seen["freeform"] = allow_freeform
            return options[0]

    register_gateway_hook(_CaptureHook())
    clarify(
        question="pick one",
        options=["x", "y", "z"],
        timeout_seconds=42,
        allow_freeform=True,
    )
    assert seen == {
        "q": "pick one",
        "opts": ["x", "y", "z"],
        "timeout": 42,
        "freeform": True,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_empty_options_errors() -> None:
    result = clarify(question="?", options=[])
    assert result.startswith("ERROR")


def test_none_options_errors() -> None:
    result = clarify(question="?", options=None)
    assert result.startswith("ERROR")


# ---------------------------------------------------------------------------
# Stdin resolution (pure unit tests on _resolve_line)
# ---------------------------------------------------------------------------


def test_resolve_numeric_in_range() -> None:
    assert _resolve_line("2", ["A", "B", "C"], allow_freeform=False) == "B"


def test_resolve_numeric_out_of_range_returns_input() -> None:
    """A digit outside the option range falls through; the agent
    sees the raw input and can decide what to do."""
    assert _resolve_line("99", ["A", "B"], allow_freeform=False) == "99"


def test_resolve_exact_label_match_case_insensitive() -> None:
    assert _resolve_line("yes", ["Yes", "No"], allow_freeform=False) == "Yes"


def test_resolve_prefix_match() -> None:
    """'y' uniquely prefixes 'Yes' -> 'Yes'."""
    assert _resolve_line("y", ["Yes", "No"], allow_freeform=False) == "Yes"


def test_resolve_ambiguous_prefix_falls_through() -> None:
    """'a' prefixes both 'apple' and 'aardvark'; the prefix match
    requires uniqueness, so we fall through to verbatim."""
    assert _resolve_line("a", ["apple", "aardvark"], allow_freeform=False) == "a"


def test_resolve_freeform_passes_through() -> None:
    """Even without allow_freeform, an unmatched input returns
    verbatim. allow_freeform mostly affects the prompt wording."""
    assert _resolve_line("custom", ["A", "B"], allow_freeform=True) == "custom"


def test_resolve_empty_line_falls_through() -> None:
    """An empty line shouldn't prefix-match anything; falls through."""
    assert _resolve_line("", ["A", "B"], allow_freeform=False) == ""


# ---------------------------------------------------------------------------
# Stdin path end-to-end (monkeypatch input())
# ---------------------------------------------------------------------------


def test_stdin_numeric_selection(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")
    result = clarify(question="?", options=["X", "Y", "Z"], timeout_seconds=5)
    assert result == "Y"


def test_stdin_freeform_disabled_falls_back_to_prefix_match(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    result = clarify(question="?", options=["X", "Y", "Z"], timeout_seconds=5)
    assert result == "Y"


def test_stdin_freeform_enabled_returns_raw_text(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "something else entirely")
    result = clarify(
        question="?",
        options=["X", "Y", "Z"],
        timeout_seconds=5,
        allow_freeform=True,
    )
    assert result == "something else entirely"


def test_stdin_eof_returns_no_answer(monkeypatch) -> None:
    """Reading from a closed stdin raises EOFError; the tool surfaces
    'no answer received' rather than propagating the exception."""

    def _raise_eof(_prompt: str) -> str:
        raise EOFError()

    monkeypatch.setattr("builtins.input", _raise_eof)
    result = clarify(question="?", options=["A", "B"], timeout_seconds=5)
    assert "no answer received" in result.lower()


def test_stdin_timeout_returns_no_answer(monkeypatch) -> None:
    """A slow input() call exceeds the timeout; tool surfaces
    'no answer received (timeout after Ns)'."""

    def _slow(_prompt: str) -> str:
        time.sleep(5)
        return "too late"

    monkeypatch.setattr("builtins.input", _slow)
    result = clarify(question="?", options=["A", "B"], timeout_seconds=1)
    assert "timeout" in result.lower()
    assert "no answer received" in result.lower()
