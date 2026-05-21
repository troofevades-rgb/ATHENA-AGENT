"""T7-01.1 — RunResult tests.

Pins the exit-code mapping (stable across modes) + the
JSON envelope shape (the contract a batch runner / cron job /
eval harness reads).
"""

from __future__ import annotations

import json

import pytest

from athena.headless.result import RunResult, mint_run_id


# ---------------------------------------------------------------
# mint_run_id
# ---------------------------------------------------------------


def test_mint_run_id_has_stable_prefix():
    rid = mint_run_id()
    assert rid.startswith("r-")
    # 12 hex chars of uuid
    assert len(rid) == 2 + 12


def test_mint_run_id_is_unique_per_call():
    ids = {mint_run_id() for _ in range(50)}
    assert len(ids) == 50


# ---------------------------------------------------------------
# exit code per status
# ---------------------------------------------------------------


def _r(**overrides):
    base = dict(
        run_id="r-test",
        status="ok",
        started_at="2026-05-21T00:00:00.000000Z",
        finished_at="2026-05-21T00:00:01.000000Z",
        duration_s=1.0,
        task="hello",
        workspace="/tmp",
        model="m",
        profile="default",
    )
    base.update(overrides)
    return RunResult(**base)


@pytest.mark.parametrize("status,code", [
    ("ok", 0),
    ("error", 1),
    ("invalid", 2),
    ("timeout", 124),
    ("interrupted", 130),
])
def test_exit_code_per_status(status, code):
    r = _r(status=status)
    assert r.exit_code() == code


# ---------------------------------------------------------------
# to_dict / to_json
# ---------------------------------------------------------------


def test_to_dict_contains_all_required_keys():
    r = _r()
    d = r.to_dict()
    required = {
        "run_id", "status", "exit_code",
        "started_at", "finished_at", "duration_s",
        "task", "workspace", "model", "profile",
        "session_id", "tool_calls", "tokens",
        "cost_est", "assistant_text", "error",
    }
    assert required <= set(d.keys())


def test_to_dict_includes_computed_exit_code():
    """The exit_code field in the dict matches result.exit_code()
    so a JSON consumer doesn't have to re-compute from status."""
    r = _r(status="timeout")
    d = r.to_dict()
    assert d["exit_code"] == 124


def test_to_json_round_trips():
    r = _r(
        status="error",
        error="RuntimeError: model unreachable",
        tool_calls=[{"name": "Bash", "count": 3}],
        tokens={"prompt": 100, "completion": 50,
                "cache_read": 80, "cache_creation": 20},
        cost_est=0.0042,
    )
    parsed = json.loads(r.to_json())
    assert parsed["status"] == "error"
    assert parsed["tool_calls"] == [{"name": "Bash", "count": 3}]
    assert parsed["tokens"]["prompt"] == 100
    # cost_est rounded to 6 decimals
    assert parsed["cost_est"] == 0.0042


def test_to_json_is_single_line_by_default():
    """Default --json output is one line so callers can
    line-split a batch's combined stderr-redirect."""
    r = _r()
    s = r.to_json()
    assert "\n" not in s


def test_to_json_indent_for_human_inspection():
    r = _r()
    s = r.to_json(indent=2)
    assert "\n" in s
    assert s.startswith("{\n")


def test_assistant_text_capped_with_truncation_marker():
    long = "x" * 12000
    r = _r(assistant_text=long, session_id="s-1")
    d = r.to_dict()
    assert "[truncated" in d["assistant_text"]
    assert "s-1" in d["assistant_text"]
    # Capped at ~8000 + marker
    assert len(d["assistant_text"]) < 8500


def test_short_assistant_text_not_truncated():
    r = _r(assistant_text="short answer.")
    assert r.to_dict()["assistant_text"] == "short answer."


def test_default_field_values():
    r = _r()
    assert r.error is None
    assert r.session_id is None
    assert r.tool_calls == []
    assert r.tokens == {}
    assert r.cost_est == 0.0
    assert r.assistant_text == ""
