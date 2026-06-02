"""``Agent.reset()`` -- ``/clear`` truly means clear.

Round 2 godmode follow-ups (B + C): the close-out for /godmode also
exposed a broader bug in the ``/clear`` slash command. ``reset()``
historically wiped ``self.messages`` and ``self.stats`` but ignored
two side channels that survive across the reset and leak into the
next turn:

  * ``_active_godmode`` -- the per-session jailbreak marker. Without
    a drop, ``/godmode list`` would render the ``(active)`` marker
    after ``/clear`` despite the steer that carried the jailbreak
    being gone from history (a stale-marker lie).
  * ``GLOBAL_STEER_QUEUE`` entries for this session. Pre-existing
    /steer queue plus the new /godmode apply both push here. A
    steer pushed before ``/clear`` would still fire on the next
    prompt, surprising operators who think clear cleared
    everything.

This file pins both invariants. The reset() drop of
``_active_godmode`` and the steer drain are general-purpose -- the
test file lives here (under tests/agent/) rather than tests/commands/
because ``Agent`` construction needs the ``fake_provider`` fixture
from tests/agent/conftest.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from athena.agent.core import Agent
from athena.config import Config
from athena.steer.queue import GLOBAL_STEER_QUEUE

if TYPE_CHECKING:
    from .conftest import FakeProvider


def _make_agent(fake_provider: FakeProvider, workspace: Path) -> Agent:
    return Agent(Config(model="fake-model"), workspace, provider=fake_provider)


def test_reset_drops_active_godmode_marker(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """After ``/clear``, the active strategy marker must NOT
    persist -- otherwise ``/godmode list`` lies about live state."""
    agent = _make_agent(fake_provider, workspace)
    agent._active_godmode = {
        "strategy": "og_godmode",
        "applied_at": "2026-01-01T00:00:00+00:00",
    }

    agent.reset()

    assert getattr(agent, "_active_godmode", None) is None


def test_reset_drains_pending_steers(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """A steer pushed (by ``/steer`` or ``/godmode apply``) before
    ``/clear`` must NOT fire on the next prompt -- ``/clear``
    drains the per-session queue."""
    agent = _make_agent(fake_provider, workspace)
    assert agent.session_id is not None
    try:
        GLOBAL_STEER_QUEUE.push(agent.session_id, "do this thing")
        GLOBAL_STEER_QUEUE.push(agent.session_id, "and this too")
        assert len(GLOBAL_STEER_QUEUE.list(agent.session_id)) == 2

        agent.reset()

        assert GLOBAL_STEER_QUEUE.list(agent.session_id) == []
    finally:
        # Belt-and-suspenders cleanup in case the assertion fires
        # before agent.reset() runs.
        GLOBAL_STEER_QUEUE.clear(agent.session_id)


def test_reset_when_no_godmode_marker_present_does_not_crash(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """Sessions that never touched /godmode have no
    ``_active_godmode`` attribute. reset() must not crash on the
    lookup -- ``hasattr`` guards the drop."""
    agent = _make_agent(fake_provider, workspace)
    assert not hasattr(agent, "_active_godmode")

    agent.reset()  # Must not raise.


def test_reset_with_no_session_id_does_not_crash(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """A degenerate agent without a ``session_id`` (sub-agent
    stub, failed init) must still be resettable -- the steer-drain
    branch is guarded on ``session_id is not None``."""
    agent = _make_agent(fake_provider, workspace)
    agent.session_id = None  # type: ignore[assignment]

    agent.reset()  # Must not raise.


def test_reset_does_not_touch_other_sessions_steers(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """The drain is per-session: steers queued for OTHER session
    ids must survive this agent's reset. Otherwise a forked agent's
    /clear would silently break the parent's pending steers."""
    agent = _make_agent(fake_provider, workspace)
    assert agent.session_id is not None
    other_session = "some-other-session"
    try:
        GLOBAL_STEER_QUEUE.push(agent.session_id, "for me")
        GLOBAL_STEER_QUEUE.push(other_session, "for someone else")

        agent.reset()

        assert GLOBAL_STEER_QUEUE.list(agent.session_id) == []
        assert GLOBAL_STEER_QUEUE.list(other_session) == ["for someone else"]
    finally:
        GLOBAL_STEER_QUEUE.clear(agent.session_id)
        GLOBAL_STEER_QUEUE.clear(other_session)
