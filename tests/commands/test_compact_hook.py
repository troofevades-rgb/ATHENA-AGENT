"""User-model ingestion fires on a background thread — but ONLY when
configured. Exercises the consolidated trigger in
``athena.user_model.ingest`` used by both /compact and session close."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from athena.config import Config, UserModelConfig
from athena.user_model.ingest import maybe_fire_ingest


def _wait_for_threads_named(prefix: str, timeout: float = 2.0) -> bool:
    """Spin briefly waiting for our worker thread to finish.
    Avoids flake by giving the daemon a chance to run on slow CI."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(t.name.startswith(prefix) for t in threading.enumerate() if t.is_alive()):
            return True
        time.sleep(0.02)
    return False


def _make_agent(cfg: Config) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=cfg,
        model="test-model",
        provider=MagicMock(),
        session_id="test-session",
    )


def test_no_fire_when_backend_none():
    """Backend = 'none' is the explicit opt-out — must not even spawn a
    thread, never mind call the LLM."""
    cfg = Config(user_model=UserModelConfig(backend="none", ingest_on_compact=True))
    agent = _make_agent(cfg)
    assert maybe_fire_ingest(agent, [{"role": "user", "content": "hi"}], trigger="compact") is False


def test_no_fire_when_compact_flag_off():
    """``ingest_on_compact = False`` skips the compact trigger even on
    the default markdown backend."""
    cfg = Config(user_model=UserModelConfig(backend="markdown", ingest_on_compact=False))
    agent = _make_agent(cfg)
    assert maybe_fire_ingest(agent, [{"role": "user", "content": "hi"}], trigger="compact") is False


def test_no_fire_when_session_end_flag_off():
    """``ingest_on_session_end = False`` skips the session-end trigger."""
    cfg = Config(
        user_model=UserModelConfig(backend="markdown", ingest_on_session_end=False),
    )
    agent = _make_agent(cfg)
    assert (
        maybe_fire_ingest(agent, [{"role": "user", "content": "hi"}], trigger="session_end")
        is False
    )


def test_fires_on_session_end_when_enabled():
    """The previously-dead ingest_on_session_end (default True) now
    actually starts a worker for the markdown backend."""
    cfg = Config(
        user_model=UserModelConfig(backend="markdown", ingest_on_session_end=True),
    )
    agent = _make_agent(cfg)
    assert (
        maybe_fire_ingest(agent, [{"role": "user", "content": "hi"}], trigger="session_end")
        is True
    )
    # The daemon worker eventually finishes (extraction is best-effort).
    assert _wait_for_threads_named("athena-user-model-ingest")


def test_session_end_uses_independent_provider(monkeypatch):
    """Regression: session-end ingest fires from inside Agent.close(),
    which tears down the agent's provider moments later. The worker must
    build (and close) an INDEPENDENT auxiliary provider instead of
    reusing the agent's — otherwise the extraction LLM call races the
    close and almost always fails."""
    import athena.agent.auxiliary_client as aux_mod
    import athena.user_model as um_mod

    aux_provider = MagicMock()
    built = {"n": 0}

    def _fake_build(_agent):
        built["n"] += 1
        return aux_provider

    monkeypatch.setattr(aux_mod, "build_auxiliary_client", _fake_build)

    fake_backend = MagicMock()

    async def _ingest(*_a, **_k):
        return None

    fake_backend.ingest_session = _ingest
    monkeypatch.setattr(um_mod, "get_user_model_backend", lambda *_a, **_k: fake_backend)

    cfg = Config(user_model=UserModelConfig(backend="markdown", ingest_on_session_end=True))
    agent = _make_agent(cfg)
    assert (
        maybe_fire_ingest(agent, [{"role": "user", "content": "x"}], trigger="session_end") is True
    )
    assert _wait_for_threads_named("athena-user-model-ingest")
    # Built exactly one independent provider, and closed it afterwards.
    assert built["n"] == 1
    aux_provider.close.assert_called_once()


def test_no_fire_on_empty_transcript():
    cfg = Config(user_model=UserModelConfig(backend="markdown", ingest_on_session_end=True))
    agent = _make_agent(cfg)
    assert maybe_fire_ingest(agent, [], trigger="session_end") is False


def test_unknown_trigger_does_not_fire():
    cfg = Config(user_model=UserModelConfig(backend="markdown"))
    agent = _make_agent(cfg)
    assert maybe_fire_ingest(agent, [{"role": "user", "content": "x"}], trigger="bogus") is False


def test_no_fire_when_agent_has_no_cfg():
    """Defensive — a malformed agent stub must not crash."""
    agent = SimpleNamespace()
    assert maybe_fire_ingest(agent, [], trigger="session_end") is False
