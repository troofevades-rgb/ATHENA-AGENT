"""Tests for athena.tools.thrash — repeat-call detection in dispatch."""

from __future__ import annotations

import pytest

from athena.tools import thrash


@pytest.fixture(autouse=True)
def _reset_thrash():
    thrash.reset()
    yield
    thrash.reset()


# ----------------------------------------------------------------------
# precheck — does NOT fire below threshold
# ----------------------------------------------------------------------


def test_first_call_does_not_trigger():
    assert thrash.precheck("Read", {"file_path": "/a"}) is None


def test_below_threshold_does_not_trigger():
    # Threshold is 2 → one prior call isn't enough.
    thrash.record("Read", {"file_path": "/a"}, "hello")
    assert thrash.precheck("Read", {"file_path": "/a"}) is None


# ----------------------------------------------------------------------
# precheck — fires at threshold with identical args + identical results
# ----------------------------------------------------------------------


def test_threshold_identical_calls_triggers():
    thrash.record("Read", {"file_path": "/a"}, "hello")
    thrash.record("Read", {"file_path": "/a"}, "hello")
    warning = thrash.precheck("Read", {"file_path": "/a"})
    assert warning is not None
    assert "THRASH WARNING" in warning
    assert "'Read'" in warning
    assert "hello" in warning  # prior result preview surfaced


# ----------------------------------------------------------------------
# precheck — does NOT fire when results differ (polling pattern)
# ----------------------------------------------------------------------


def test_same_args_different_results_does_not_trigger():
    """Bash `date` returns a different value each second — that's a
    legitimate polling pattern, not thrash."""
    thrash.record("Bash", {"command": "date"}, "Mon May 21 10:00:00")
    thrash.record("Bash", {"command": "date"}, "Mon May 21 10:00:01")
    assert thrash.precheck("Bash", {"command": "date"}) is None


# ----------------------------------------------------------------------
# precheck — does NOT fire when args differ
# ----------------------------------------------------------------------


def test_different_args_does_not_trigger():
    thrash.record("Read", {"file_path": "/a"}, "x")
    thrash.record("Read", {"file_path": "/a"}, "x")
    assert thrash.precheck("Read", {"file_path": "/b"}) is None


def test_different_tool_does_not_trigger():
    thrash.record("Read", {"file_path": "/a"}, "x")
    thrash.record("Read", {"file_path": "/a"}, "x")
    assert thrash.precheck("Grep", {"file_path": "/a"}) is None


# ----------------------------------------------------------------------
# precheck — recovers after a non-identical call breaks the streak
# ----------------------------------------------------------------------


def test_streak_broken_by_intervening_call():
    """If the model varies its calls, the streak should reset."""
    thrash.record("Read", {"file_path": "/a"}, "x")
    thrash.record("Read", {"file_path": "/b"}, "y")
    thrash.record("Read", {"file_path": "/a"}, "x")
    # Only one /a call in the last 2 entries → not thrash.
    assert thrash.precheck("Read", {"file_path": "/a"}) is None


# ----------------------------------------------------------------------
# Long results get truncated in the preview
# ----------------------------------------------------------------------


def test_long_result_preview_is_truncated():
    big = "X" * (thrash.PREVIEW_CHARS + 500)
    thrash.record("Read", {"file_path": "/a"}, big)
    thrash.record("Read", {"file_path": "/a"}, big)
    warning = thrash.precheck("Read", {"file_path": "/a"})
    assert warning is not None
    assert "truncated" in warning


# ----------------------------------------------------------------------
# reset() clears the buffer
# ----------------------------------------------------------------------


def test_reset_clears_history():
    thrash.record("Read", {"file_path": "/a"}, "x")
    thrash.record("Read", {"file_path": "/a"}, "x")
    thrash.reset()
    # Buffer empty → next call doesn't trigger.
    assert thrash.precheck("Read", {"file_path": "/a"}) is None


# ----------------------------------------------------------------------
# Integration with dispatch — synthetic warning replaces the real call
# ----------------------------------------------------------------------


def test_dispatch_returns_warning_on_third_identical_call(monkeypatch):
    """Three identical calls in dispatch → third gets the warning."""
    from athena.tools import registry

    call_count = {"n": 0}

    def _fake_tool(file_path: str) -> str:
        call_count["n"] += 1
        return "stable-result"

    # Register a temporary tool just for this test.
    from athena.tools.registry import Tool, _REGISTRY

    saved = _REGISTRY.get("__thrash_test_tool")
    _REGISTRY["__thrash_test_tool"] = Tool(
        name="__thrash_test_tool",
        toolset="test",
        description="x",
        parameters={
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
        func=_fake_tool,
    )
    try:
        out1 = registry.dispatch("__thrash_test_tool", {"file_path": "/a"})
        out2 = registry.dispatch("__thrash_test_tool", {"file_path": "/a"})
        out3 = registry.dispatch("__thrash_test_tool", {"file_path": "/a"})
        assert out1 == "stable-result"
        assert out2 == "stable-result"
        assert "THRASH WARNING" in out3
        # The synthetic warning bypassed the underlying tool function.
        assert call_count["n"] == 2
    finally:
        if saved is None:
            del _REGISTRY["__thrash_test_tool"]
        else:
            _REGISTRY["__thrash_test_tool"] = saved
