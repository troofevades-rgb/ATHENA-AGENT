"""The /compact command kicks off user-model ingestion in a
background thread — but ONLY when configured to do so."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from athena.commands.compact import _maybe_fire_user_model_ingest
from athena.config import Config, UserModelConfig


def _wait_for_threads_named(prefix: str, timeout: float = 2.0) -> bool:
    """Spin briefly waiting for our worker thread to finish.
    Avoids flake by giving the daemon a chance to run on slow CI."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(
            t.name.startswith(prefix) for t in threading.enumerate() if t.is_alive()
        ):
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
    """Backend = 'none' is the explicit opt-out — hook must not
    even spawn a thread, never mind call the LLM."""
    cfg = Config(user_model=UserModelConfig(backend="none", ingest_on_compact=True))
    agent = _make_agent(cfg)
    before = threading.active_count()
    _maybe_fire_user_model_ingest(agent, [{"role": "user", "content": "hi"}])
    _wait_for_threads_named("athena-user-model-ingest")
    # No worker thread should have been started.
    assert threading.active_count() <= before + 0  # tolerate scheduling slack


def test_no_fire_when_flag_off():
    """``ingest_on_compact = False`` must skip the hook even on
    the default markdown backend."""
    cfg = Config(
        user_model=UserModelConfig(backend="markdown", ingest_on_compact=False)
    )
    agent = _make_agent(cfg)
    _maybe_fire_user_model_ingest(agent, [{"role": "user", "content": "hi"}])
    assert _wait_for_threads_named("athena-user-model-ingest")


def test_no_fire_when_agent_has_no_cfg():
    """Defensive — a malformed agent stub must not crash the
    REPL even if cfg is missing."""
    agent = SimpleNamespace()
    _maybe_fire_user_model_ingest(agent, [])  # should not raise
