"""Tests for ocode.curator.orchestrator.maybe_run_curator.

These tests exercise the gate logic + YAML round-trip without spinning up
a real Ollama: ocode.agent.fork.fork is monkey-patched to return a pre-
canned ForkResult.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ocode.agent.fork import ForkResult
from ocode.config import CONFIG_DIR, Config, CuratorConfig
from ocode.curator import orchestrator, state


VALID_YAML = """\
```yaml-curator-report
runs:
  - skill: foo
    decision: KEEP_AS_IS
    target: null
    rationale: still relevant
```
"""

INVALID_YAML = "no yaml here, sorry"


def _agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    last_other_ended_at: datetime | None = None,
) -> SimpleNamespace:
    """Build a duck-typed Agent that satisfies the orchestrator's interface."""
    cfg = Config()
    cfg.curator = CuratorConfig(interval_hours=168, min_idle_hours=2, max_iterations=99)

    store = MagicMock()
    if last_other_ended_at is None:
        store.most_recent_other_session.return_value = None
    else:
        store.most_recent_other_session.return_value = SimpleNamespace(
            ended_at=last_other_ended_at
        )

    agent = SimpleNamespace(
        cfg=cfg,
        session_id="parent-sid",
        session_store=store,
        workspace=tmp_path,
        client=None,
        model="qwen",
    )

    # Redirect CONFIG_DIR to tmp_path so the .curator_state lives in isolation.
    monkeypatch.setattr(orchestrator, "CONFIG_DIR", tmp_path)
    return agent


def _patch_fork(monkeypatch, *, response: str, captured: list | None = None):
    calls: list = captured if captured is not None else []

    def fake_fork(parent, **kwargs):
        calls.append(kwargs)
        return ForkResult(final_response=response)

    monkeypatch.setattr("ocode.agent.fork.fork", fake_fork)
    return calls


def test_does_not_run_within_interval(monkeypatch, tmp_path) -> None:
    agent = _agent(monkeypatch, tmp_path)
    skills_root = tmp_path / "skills"
    state.write_state(skills_root, state.State(
        last_run_at=datetime.now(timezone.utc) - timedelta(hours=1),
        run_count=1,
    ))
    calls = _patch_fork(monkeypatch, response=VALID_YAML)
    assert orchestrator.maybe_run_curator(agent) is None
    assert calls == []


def test_does_not_run_with_recent_session_activity(monkeypatch, tmp_path) -> None:
    agent = _agent(
        monkeypatch, tmp_path,
        last_other_ended_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    calls = _patch_fork(monkeypatch, response=VALID_YAML)
    assert orchestrator.maybe_run_curator(agent) is None
    assert calls == []


def test_runs_when_gates_pass(monkeypatch, tmp_path) -> None:
    agent = _agent(
        monkeypatch, tmp_path,
        last_other_ended_at=datetime.now(timezone.utc) - timedelta(hours=10),
    )
    skills_root = tmp_path / "skills"
    state.write_state(skills_root, state.State(
        last_run_at=datetime.now(timezone.utc) - timedelta(days=8),
    ))
    calls = _patch_fork(monkeypatch, response=VALID_YAML)
    summary = orchestrator.maybe_run_curator(agent)
    assert summary is not None
    assert len(calls) == 1
    assert calls[0]["write_origin"] == "curator"
    assert calls[0]["enabled_toolsets"] == ["skills"]


def test_paused_state_blocks_run(monkeypatch, tmp_path) -> None:
    agent = _agent(monkeypatch, tmp_path)
    skills_root = tmp_path / "skills"
    state.write_state(skills_root, state.State(paused=True))
    calls = _patch_fork(monkeypatch, response=VALID_YAML)
    assert orchestrator.maybe_run_curator(agent) is None
    assert calls == []


def test_force_bypasses_gates(monkeypatch, tmp_path) -> None:
    agent = _agent(
        monkeypatch, tmp_path,
        last_other_ended_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    skills_root = tmp_path / "skills"
    state.write_state(skills_root, state.State(
        last_run_at=datetime.now(timezone.utc),
        paused=True,
    ))
    calls = _patch_fork(monkeypatch, response=VALID_YAML)
    summary = orchestrator.maybe_run_curator(agent, force=True)
    assert summary is not None
    assert len(calls) == 1


def test_dry_run_passes_banner_to_fork(monkeypatch, tmp_path) -> None:
    agent = _agent(monkeypatch, tmp_path)
    calls = _patch_fork(monkeypatch, response=VALID_YAML)
    orchestrator.maybe_run_curator(agent, force=True, dry_run=True)
    assert calls
    addendum = calls[0]["system_addendum"]
    assert "DRY_RUN=true" in addendum
    assert "do not call destructive" in addendum.lower()


def test_invalid_yaml_output_rejects_run(monkeypatch, tmp_path) -> None:
    agent = _agent(monkeypatch, tmp_path)
    _patch_fork(monkeypatch, response=INVALID_YAML)
    summary = orchestrator.maybe_run_curator(agent, force=True)
    assert summary is None
    # State must NOT have been updated — the curator didn't really commit.
    skills_root = tmp_path / "skills"
    cur = state.read_state(skills_root)
    assert cur.last_run_at is None


def test_state_updates_on_successful_run(monkeypatch, tmp_path) -> None:
    agent = _agent(monkeypatch, tmp_path)
    _patch_fork(monkeypatch, response=VALID_YAML)
    summary = orchestrator.maybe_run_curator(agent, force=True)
    assert summary is not None
    cur = state.read_state(tmp_path / "skills")
    assert cur.last_run_at is not None
    assert cur.run_count == 1
