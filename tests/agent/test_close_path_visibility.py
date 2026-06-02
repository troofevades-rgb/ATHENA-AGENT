"""0.3.0 hardening tier 1 (A) -- Agent.close() teardown is observable.

The close path runs a fan-out of "best-effort" cleanup steps: plugin
on_session_end, review nudge reset, httpx client close, session-store
close, browser-session teardown. Each one historically swallowed
exceptions with bare ``except Exception: pass`` so a buggy plugin or a
half-initialized session store couldn't break shutdown.

That was right -- but invisible. If the gateway daemon's per-session
cleanup quietly fails for every conversation, operators have no
signal. The fix replaces the silent swallows with ``logger.debug(...,
exc_info=True)`` (matching the sibling closures at lines 856/862),
which keeps the swallow semantics for callers but makes failures
discoverable at DEBUG.

Pins:

  * A raising plugin ``on_session_end`` does NOT escape ``close()``.
  * The same failure emits exactly one ``logger.debug`` record with
    the traceback attached (``exc_info`` is set).
  * The debug message identifies which cleanup step raised, so a
    log dive points at the failing component instead of a generic
    "close raised".
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from athena.agent.core import Agent
from athena.config import Config

if TYPE_CHECKING:
    from .conftest import FakeProvider


def _make_agent(fake_provider: FakeProvider, workspace: Path) -> Agent:
    cfg = Config(model="fake-model")
    return Agent(cfg, workspace, provider=fake_provider)


def test_close_swallows_plugin_hook_exception(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """A raising plugin on_session_end must not escape Agent.close()."""
    agent = _make_agent(fake_provider, workspace)

    def _boom(*_a: object, **_kw: object) -> None:
        raise RuntimeError("plugin blew up")

    agent.plugin_hooks.on_session_end = _boom  # type: ignore[assignment]

    # The whole point: close() must complete without raising.
    agent.close()


def test_close_logs_plugin_failure_at_debug(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When a cleanup step raises, the failure surfaces in DEBUG logs
    with exc_info attached -- so operators tail-ing logs at DEBUG can
    see what broke without having to add print() statements."""
    agent = _make_agent(fake_provider, workspace)

    def _boom(*_a: object, **_kw: object) -> None:
        raise RuntimeError("plugin boom")

    agent.plugin_hooks.on_session_end = _boom  # type: ignore[assignment]

    with caplog.at_level(logging.DEBUG, logger="athena.agent.lifecycle"):
        agent.close()

    # Exactly one debug record identifying the plugin hook as the
    # source. ``exc_info`` must be set so the traceback is attached
    # and a future log-aggregator can extract the stack.
    matches = [
        r
        for r in caplog.records
        if r.levelno == logging.DEBUG and "plugin on_session_end" in r.getMessage()
    ]
    assert len(matches) == 1, (
        f"expected one debug record for plugin hook failure, got "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )
    assert matches[0].exc_info is not None
    # And the traceback specifically captures *our* RuntimeError so
    # operators can grep for it in production logs.
    assert matches[0].exc_info[0] is RuntimeError


def test_close_logs_each_failing_step_distinctly(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If multiple cleanup steps fail (plugin AND client.close), each
    failure must produce its own debug record naming its component --
    not a single generic "close raised" entry."""
    agent = _make_agent(fake_provider, workspace)

    def _boom_plugin(*_a: object, **_kw: object) -> None:
        raise RuntimeError("plugin")

    def _boom_client() -> None:
        raise RuntimeError("client")

    agent.plugin_hooks.on_session_end = _boom_plugin  # type: ignore[assignment]
    # Force the client.close branch even if the agent doesn't own it
    # in this fixture; the explicit assignment + flag flip routes it
    # through the logged finally block.
    agent._owns_client = True
    agent.client.close = _boom_client  # type: ignore[assignment]

    with caplog.at_level(logging.DEBUG, logger="athena.agent.lifecycle"):
        agent.close()

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("plugin on_session_end" in m for m in messages), messages
    assert any("client.close" in m for m in messages), messages
