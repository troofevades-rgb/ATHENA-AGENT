"""Tests for the per-turn review orchestrator."""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

from athena.config import Config
from athena.review import nudge
from athena.review.orchestrator import maybe_fire_review


@pytest.fixture(autouse=True)
def _clean_state():
    nudge.reset_all()
    yield
    nudge.reset_all()


def _agent_stub(
    *,
    session_id: str | None = "sess-1",
    cfg: Config | None = None,
    messages: list[dict] | None = None,
) -> Any:
    """A duck-typed Agent suitable for orchestrator.maybe_fire_review."""
    agent = MagicMock()
    agent.cfg = cfg or Config()
    agent.session_id = session_id
    agent.messages = messages or [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    agent.last_review_summary = None
    return agent


def test_does_not_fire_below_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    spawned: list[bool] = []
    monkeypatch.setattr(
        "athena.agent.fork.fork",
        lambda *a, **k: spawned.append(True) or None,
    )
    agent = _agent_stub()
    agent.cfg.review.nudge_interval = 10
    for _ in range(9):
        assert maybe_fire_review(agent) is None
    assert spawned == []


def test_fires_at_interval_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """The orchestrator spawns a daemon thread on the Nth call."""
    calls: list[dict] = []

    def fake_fork(parent, **kwargs):
        calls.append(kwargs)
        from athena.agent.fork import ForkResult

        return ForkResult(final_response="ok")

    monkeypatch.setattr("athena.agent.fork.fork", fake_fork)

    agent = _agent_stub()
    agent.cfg.review.nudge_interval = 3
    for _ in range(2):
        assert maybe_fire_review(agent) is None
    t = maybe_fire_review(agent)
    assert isinstance(t, threading.Thread)
    t.join(timeout=2)
    assert calls, "fork should have been called once"


def test_review_fork_uses_correct_toolsets(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_fork(parent, **kwargs):
        calls.append(kwargs)
        from athena.agent.fork import ForkResult

        return ForkResult(final_response="")

    monkeypatch.setattr("athena.agent.fork.fork", fake_fork)
    agent = _agent_stub(cfg=Config())
    agent.cfg.review.nudge_interval = 1
    t = maybe_fire_review(agent)
    t.join(timeout=2)
    assert set(calls[0]["enabled_toolsets"]) == {"memory", "skills"}


def test_review_fork_write_origin_is_background_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def fake_fork(parent, **kwargs):
        calls.append(kwargs)
        from athena.agent.fork import ForkResult

        return ForkResult(final_response="")

    monkeypatch.setattr("athena.agent.fork.fork", fake_fork)
    agent = _agent_stub()
    agent.cfg.review.nudge_interval = 1
    t = maybe_fire_review(agent)
    t.join(timeout=2)
    assert calls[0]["write_origin"] == "background_review"


def test_review_fork_inherits_last_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_fork(parent, **kwargs):
        calls.append(kwargs)
        from athena.agent.fork import ForkResult

        return ForkResult(final_response="")

    monkeypatch.setattr("athena.agent.fork.fork", fake_fork)
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u3"},
    ]
    agent = _agent_stub(messages=msgs)
    agent.cfg.review.nudge_interval = 1
    t = maybe_fire_review(agent)
    t.join(timeout=2)
    history = calls[0]["conversation_history"]
    # Tail of length 4
    assert len(history) == 4
    assert history[-1]["content"] == "u3"


def test_review_disabled_via_config_skips_fire(monkeypatch: pytest.MonkeyPatch) -> None:
    fired: list[bool] = []
    monkeypatch.setattr(
        "athena.agent.fork.fork",
        lambda *a, **k: fired.append(True) or None,
    )
    agent = _agent_stub()
    agent.cfg.review.disabled = True
    agent.cfg.review.nudge_interval = 1
    assert maybe_fire_review(agent) is None
    assert fired == []


def test_review_fork_fire_and_forget(monkeypatch: pytest.MonkeyPatch) -> None:
    """The orchestrator must return a daemon thread that the caller is NOT
    required to join — it's a fire-and-forget contract."""
    monkeypatch.setattr(
        "athena.agent.fork.fork",
        lambda *a, **k: __import__("athena.agent.fork", fromlist=["ForkResult"]).ForkResult(
            final_response=""
        ),
    )
    agent = _agent_stub()
    agent.cfg.review.nudge_interval = 1
    t = maybe_fire_review(agent)
    assert t is not None
    assert t.daemon is True


def test_review_skipped_when_session_id_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fired: list[bool] = []
    monkeypatch.setattr(
        "athena.agent.fork.fork",
        lambda *a, **k: fired.append(True) or None,
    )
    agent = _agent_stub(session_id=None)
    agent.cfg.review.nudge_interval = 1
    assert maybe_fire_review(agent) is None
    assert fired == []
