"""Tests for ``/status`` — render the session snapshot.

The slash command is a thin wrapper that builds a snapshot from
``agent.stats.to_snapshot`` + optional provider extras, then hands
it to ``athena.cli.status.render_status``. We verify the snapshot
shape it produces, including the optional rate-limit + retry-count
grafts when the provider exposes them.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from athena.commands.status_cmd import cmd_status


def _capture():
    lines: list[str] = []
    patches = [
        patch(
            "athena.commands.status_cmd.ui.console.print",
            side_effect=lambda *a, **kw:
                lines.append(" ".join(str(x) for x in a)),
        ),
    ]
    return lines, patches


def _run(agent) -> str:
    lines, patches = _capture()
    for p in patches:
        p.start()
    try:
        cmd_status(agent, "")
    finally:
        for p in patches:
            p.stop()
    return "\n".join(lines)


def _fake_agent(
    *,
    rate_limit_state=None,
    retry_counts=None,
    snapshot_extras: dict | None = None,
):
    snapshot = {
        "profile": "default",
        "session_id": "s-1",
        "model": "qwen",
        "provider": "ollama",
        "turns": 3,
    }
    if snapshot_extras:
        snapshot.update(snapshot_extras)

    provider = SimpleNamespace(name="ollama")
    if rate_limit_state is not None:
        provider.get_rate_limit_state = lambda: rate_limit_state
    if retry_counts is not None:
        provider.get_retry_counts = lambda: retry_counts

    return SimpleNamespace(
        stats=SimpleNamespace(to_snapshot=lambda **k: dict(snapshot)),
        session_id="s-1",
        model="qwen",
        provider=provider,
        cfg=SimpleNamespace(profile="default"),
    )


# ---- basic render path ----------------------------------------------


def test_renders_via_render_status() -> None:
    captured: list[dict] = []
    agent = _fake_agent()
    with patch(
        "athena.cli.status.render_status",
        side_effect=lambda snap: (captured.append(snap), "RENDERED OUTPUT")[1],
    ):
        out = _run(agent)
    assert "RENDERED OUTPUT" in out
    assert len(captured) == 1
    snap = captured[0]
    assert snap["model"] == "qwen"
    assert snap["provider"] == "ollama"


def test_passes_default_profile_when_cfg_profile_none() -> None:
    """When cfg.profile is None/falsy, the snapshot uses 'default'."""
    agent = _fake_agent()
    agent.cfg = SimpleNamespace(profile=None)
    captured: list[dict] = []

    # Stats.to_snapshot receives the profile kwarg — capture what's
    # passed by instrumenting the stats fake.
    received_kwargs: dict = {}
    agent.stats = SimpleNamespace(
        to_snapshot=lambda **k: (received_kwargs.update(k), {
            "profile": k["profile"], "model": "qwen",
            "provider": "ollama", "session_id": "s-1",
        })[1],
    )
    with patch(
        "athena.cli.status.render_status",
        side_effect=lambda snap: (captured.append(snap), "ok")[1],
    ):
        _run(agent)
    assert received_kwargs["profile"] == "default"


# ---- rate-limit graft ----------------------------------------------


def test_rate_limit_state_grafted_when_provider_exposes_it() -> None:
    """T2-02: provider's get_rate_limit_state() output is added
    to the snapshot under 'rate_limits' before rendering."""
    tracker = SimpleNamespace(format=lambda: "ratelimited until 12:00")
    agent = _fake_agent(rate_limit_state={"cred-1": tracker, "cred-2": tracker})
    captured: list[dict] = []
    with patch(
        "athena.cli.status.render_status",
        side_effect=lambda snap: (captured.append(snap), "")[1],
    ):
        _run(agent)
    snap = captured[0]
    assert "rate_limits" in snap
    assert snap["rate_limits"] == {
        "cred-1": "ratelimited until 12:00",
        "cred-2": "ratelimited until 12:00",
    }


def test_no_rate_limit_graft_when_provider_lacks_accessor() -> None:
    """Most providers don't expose get_rate_limit_state. The snapshot
    must not gain a stray 'rate_limits' key."""
    agent = _fake_agent()
    # Ensure no get_rate_limit_state attribute
    assert not hasattr(agent.provider, "get_rate_limit_state")
    captured: list[dict] = []
    with patch(
        "athena.cli.status.render_status",
        side_effect=lambda snap: (captured.append(snap), "")[1],
    ):
        _run(agent)
    assert "rate_limits" not in captured[0]


# ---- retry-count graft ---------------------------------------------


def test_retry_counts_grafted_when_provider_exposes_it() -> None:
    """T2-03.9: provider's get_retry_counts() output is added to
    the snapshot under 'retry_counts' keyed by provider name."""
    agent = _fake_agent(retry_counts={"429": 3, "500": 1, "aborted": 0})
    captured: list[dict] = []
    with patch(
        "athena.cli.status.render_status",
        side_effect=lambda snap: (captured.append(snap), "")[1],
    ):
        _run(agent)
    snap = captured[0]
    assert "retry_counts" in snap
    # Keyed by provider name from snapshot
    assert snap["retry_counts"] == {
        "ollama": {"429": 3, "500": 1, "aborted": 0},
    }
