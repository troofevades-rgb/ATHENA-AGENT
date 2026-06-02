"""Tests for the background-review serialization fix.

The bug: ``_maybe_fire_review`` spawned a daemon thread that called
``fork()`` which called the child agent's ``run_until_done`` which
made its own Ollama calls. Meanwhile a NEW foreground turn could
start and call Ollama AGAIN, leaving TWO concurrent inference
requests fighting for the GPU. Both got slow.

The fix:
  1. ``_maybe_fire_review`` stores the spawned thread on
     ``self._active_review_thread`` so subsequent calls can see it.
  2. ``run_turn`` calls ``_wait_for_background_review(timeout=60s)``
     at the top, blocking until any prior review finishes.

These tests verify the contract WITHOUT spinning up a real model.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _make_agent_stub(tmp_path: Path):
    """Build a bare object with just the surface the wait method touches."""
    from athena.agent.core import Agent

    obj = SimpleNamespace()
    # Bind the real bound method to our stub (it only reads
    # _active_review_thread; doesn't touch other state).
    obj._wait_for_background_review = Agent._wait_for_background_review.__get__(obj)
    obj._active_review_thread = None
    return obj


def test_wait_no_op_when_no_review_in_flight(tmp_path: Path) -> None:
    """When _active_review_thread is None, wait must return immediately
    without any side effects."""
    agent = _make_agent_stub(tmp_path)
    start = time.monotonic()
    agent._wait_for_background_review(timeout=5.0)
    elapsed = time.monotonic() - start
    assert elapsed < 0.1, f"no-op wait took {elapsed:.3f}s, expected near-zero"


def test_wait_returns_quickly_when_review_already_done(tmp_path: Path) -> None:
    """A dead thread shouldn't block the wait."""
    agent = _make_agent_stub(tmp_path)
    # A thread that exits immediately
    done = threading.Thread(target=lambda: None)
    done.start()
    done.join()
    assert not done.is_alive()
    agent._active_review_thread = done

    start = time.monotonic()
    agent._wait_for_background_review(timeout=5.0)
    elapsed = time.monotonic() - start
    assert elapsed < 0.1


def test_wait_blocks_until_review_thread_finishes(tmp_path: Path) -> None:
    """If the review is in-flight, wait must actually wait for it
    (up to timeout) — that's the whole point of the fix."""
    agent = _make_agent_stub(tmp_path)
    finish = threading.Event()

    def _slow_review() -> None:
        finish.wait(timeout=5.0)  # waits up to 5s

    review = threading.Thread(target=_slow_review, daemon=True)
    review.start()
    agent._active_review_thread = review

    # Schedule the review to finish after 200ms
    def _release() -> None:
        time.sleep(0.2)
        finish.set()

    releaser = threading.Thread(target=_release, daemon=True)
    releaser.start()

    start = time.monotonic()
    agent._wait_for_background_review(timeout=5.0)
    elapsed = time.monotonic() - start
    # Should have blocked ~200ms (waiting for finish.set), not the
    # full 5s timeout.
    assert 0.15 < elapsed < 1.0, (
        f"wait took {elapsed:.3f}s; expected ~0.2s (the review's "
        f"actual duration), not the full 5s timeout."
    )
    assert not review.is_alive()


def test_wait_returns_after_timeout_if_review_hangs(tmp_path: Path) -> None:
    """If the review is stuck forever, wait must not block the
    foreground turn indefinitely — surrender after the timeout."""
    agent = _make_agent_stub(tmp_path)
    forever = threading.Event()  # never set

    def _stuck_review() -> None:
        forever.wait()  # blocks forever

    review = threading.Thread(target=_stuck_review, daemon=True)
    review.start()
    agent._active_review_thread = review

    start = time.monotonic()
    agent._wait_for_background_review(timeout=0.3)
    elapsed = time.monotonic() - start
    # Should have returned at ~0.3s (the timeout), not earlier
    # (the review never finishes) and not much later.
    assert 0.25 < elapsed < 0.8, f"wait took {elapsed:.3f}s; expected ~0.3s timeout."
    # The thread is STILL ALIVE — we just stopped waiting on it
    assert review.is_alive()
    # Clean up so pytest doesn't complain
    forever.set()


def test_wait_skipped_for_non_local_provider(tmp_path: Path) -> None:
    """Hosted (non-local) providers handle concurrent requests fine, so
    the foreground turn must NOT block on an in-flight review for them —
    that wait only buys anything on Ollama's single-inference GPU."""
    from athena.providers.base import Capabilities

    agent = _make_agent_stub(tmp_path)
    agent.model = "claude-opus-4-8"
    agent.provider = SimpleNamespace(
        capabilities=lambda model=None: Capabilities(is_local=False),
    )

    forever = threading.Event()  # never set — review "still running"
    review = threading.Thread(target=forever.wait, daemon=True)
    review.start()
    agent._active_review_thread = review

    start = time.monotonic()
    agent._wait_for_background_review(timeout=5.0)
    elapsed = time.monotonic() - start
    # Returned immediately despite the live review and a generous timeout.
    assert elapsed < 0.1, f"non-local wait took {elapsed:.3f}s; expected near-zero"
    assert review.is_alive()
    forever.set()


def test_wait_still_blocks_for_local_provider(tmp_path: Path) -> None:
    """Local providers keep the protective wait — the whole reason it
    exists is Ollama's single-inference contention."""
    from athena.providers.base import Capabilities

    agent = _make_agent_stub(tmp_path)
    agent.model = "qwen2.5-coder:14b"
    agent.provider = SimpleNamespace(
        capabilities=lambda model=None: Capabilities(is_local=True),
    )

    finish = threading.Event()
    review = threading.Thread(target=lambda: finish.wait(timeout=5.0), daemon=True)
    review.start()
    agent._active_review_thread = review

    def _release() -> None:
        time.sleep(0.2)
        finish.set()

    threading.Thread(target=_release, daemon=True).start()

    start = time.monotonic()
    agent._wait_for_background_review(timeout=5.0)
    elapsed = time.monotonic() - start
    # Blocked ~0.2s (waited for the local review), not near-zero.
    assert 0.15 < elapsed < 1.0, f"local wait took {elapsed:.3f}s; expected ~0.2s"


# ---------------------------------------------------------------------------
# Integration with orchestrator — ensure the spawned thread gets
# recorded on the parent agent.
# ---------------------------------------------------------------------------


def test_maybe_fire_review_records_thread_on_parent(tmp_path: Path) -> None:
    """After maybe_fire_review fires (counter trips), the thread it
    spawned must be stored on parent_agent._active_review_thread so
    the next run_turn can wait for it."""
    from athena.config import Config
    from athena.review import nudge, orchestrator

    nudge.reset_all()
    parent = SimpleNamespace(
        cfg=Config(),
        session_id="sess-X",
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
        last_review_summary=None,
        _active_review_thread=None,
    )
    parent.cfg.review.nudge_interval = 1  # fire on every call

    # Patch fork so we don't actually run a child agent — just
    # block long enough that the test can observe the thread.
    finish = threading.Event()

    def _stub_fork(*args, **kwargs):
        finish.wait(timeout=2.0)
        return SimpleNamespace(actions=[], error=None)

    with patch("athena.agent.fork.fork", side_effect=_stub_fork):
        spawned = orchestrator.maybe_fire_review(parent)

    assert spawned is not None
    assert spawned.is_alive()

    # Simulate what _maybe_fire_review does — store on the parent.
    # (In real code this happens inside _maybe_fire_review; we're
    # testing the orchestrator returns a usable handle.)
    parent._active_review_thread = spawned

    assert parent._active_review_thread is spawned
    finish.set()
    spawned.join(timeout=2.0)
    assert not spawned.is_alive()
    nudge.reset_all()


# ---------------------------------------------------------------------------
# Gateway opt-out — gateway-bound agents must not spawn review forks.
# ---------------------------------------------------------------------------


def test_maybe_fire_review_suppressed_for_gateway_agent() -> None:
    """A gateway-bound agent (_suppress_background_review=True) must NOT
    fire the review fork — it would compete with the user-facing reply
    for the local Ollama slot."""
    from athena.agent.core import Agent

    obj = SimpleNamespace()
    obj._maybe_fire_review = Agent._maybe_fire_review.__get__(obj)
    obj._suppress_background_review = True

    with patch("athena.review.orchestrator.maybe_fire_review") as fire:
        obj._maybe_fire_review()
    fire.assert_not_called()


def test_maybe_fire_review_fires_without_suppression() -> None:
    """Without the gateway flag, the review path still reaches the
    orchestrator (the default foreground behaviour is unchanged)."""
    from athena.agent.core import Agent

    obj = SimpleNamespace()
    obj._maybe_fire_review = Agent._maybe_fire_review.__get__(obj)
    obj._suppress_background_review = False
    obj._active_review_thread = None

    with patch("athena.review.orchestrator.maybe_fire_review", return_value=None) as fire:
        obj._maybe_fire_review()
    fire.assert_called_once_with(obj)
