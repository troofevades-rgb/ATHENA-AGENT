"""Malformed tool-call repair in registry.dispatch.

dispatch already failed gracefully (returned ``ERROR: …`` strings the
model sees), but the messages weren't actionable for a small/local
model: unknown tools gave no suggestion, and wrong/typo'd argument names
were silently dropped (so a missing-required failure gave an opaque
TypeError with no hint which name was wrong). These tests pin the
actionable feedback.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from athena.tools.registry import _REGISTRY, _TOOLSETS, dispatch, tool


@pytest.fixture
def probe_tool() -> Iterator[str]:
    @tool(name="_repair_probe", description="probe", parameters={}, toolset="_test")
    def _probe(file_path: str, limit: int = 10) -> str:
        return f"ok:{file_path}:{limit}"

    try:
        yield "_repair_probe"
    finally:
        _REGISTRY.pop("_repair_probe", None)
        _TOOLSETS.get("_test", set()).discard("_repair_probe")


def test_missing_required_arg_is_actionable(probe_tool: str) -> None:
    out = dispatch(probe_tool, {})
    assert "missing required argument(s): file_path" in out
    # Lists what it WILL accept so the model can fix the call.
    assert "Accepted arguments: file_path, limit" in out


def test_typod_required_arg_suggests_the_correction(probe_tool: str) -> None:
    out = dispatch(probe_tool, {"file_paht": "x"})
    assert "missing required argument(s): file_path" in out
    assert "'file_paht' looks like 'file_path'" in out


def test_unknown_extra_arg_is_noted_when_required_missing(probe_tool: str) -> None:
    # A wholly-unrelated extra arg (no close match) is reported as ignored.
    out = dispatch(probe_tool, {"q": 1})
    assert "missing required argument(s): file_path" in out
    assert "ignored unknown argument(s): q" in out


def test_valid_call_runs_and_drops_extras(probe_tool: str) -> None:
    # Required present → tool runs; an unknown extra is dropped silently
    # (unchanged behaviour) — no false-positive repair error.
    out = dispatch(probe_tool, {"file_path": "f", "bogus": 1})
    assert out == "ok:f:10"


def test_unknown_tool_suggests_nearest(probe_tool: str) -> None:
    out = dispatch("_repair_prob", {"file_path": "x"})
    assert "unknown tool '_repair_prob'" in out
    assert "Did you mean: _repair_probe" in out


def test_unknown_tool_with_no_close_match_is_plain() -> None:
    out = dispatch("zzqqxx_nope", {})
    assert "unknown tool 'zzqqxx_nope'" in out
    assert "Did you mean" not in out
