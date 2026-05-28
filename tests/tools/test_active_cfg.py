"""``athena.tools._active_cfg.active_cfg`` resolves the Config that the
active session is actually running with.

The convention (documented in ATHENA.md / CLAUDE.md): tools should read
the LIVE agent's cfg via ``get_current_agent()`` first and fall back to
disk only when no agent is bound. Several tools were silently violating
that convention; this helper centralises the lookup so session-scoped
mutations stay visible to the tools that should honour them.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from athena.tools._active_cfg import active_cfg


def test_falls_back_to_load_config_when_no_agent():
    """No active agent → ``load_config()`` is the source. This is the
    historical behaviour the helper preserves for tools that run
    outside an Agent context (CLI startup, eval bootstrap)."""
    sentinel = SimpleNamespace(model="from-disk")
    with patch(
        "athena.config.load_config", return_value=sentinel,
    ), patch(
        "athena.agent.core.get_current_agent", return_value=None,
    ):
        assert active_cfg() is sentinel


def test_prefers_live_agent_cfg_over_disk():
    """Active agent bound → its cfg wins, regardless of what's on disk.
    Session-scoped mutations (e.g. ``/allowlist add``) are then
    immediately visible to the tool layer."""
    live = SimpleNamespace(model="live-cfg", bash_allowlist=["echo"])
    disk = SimpleNamespace(model="from-disk", bash_allowlist=[])
    fake_agent = SimpleNamespace(cfg=live)
    with patch(
        "athena.agent.core.get_current_agent", return_value=fake_agent,
    ), patch(
        "athena.config.load_config", return_value=disk,
    ):
        result = active_cfg()
    assert result is live
    assert result.bash_allowlist == ["echo"]


def test_falls_back_when_agent_has_no_cfg():
    """Defensive: a malformed agent (no ``cfg`` attribute) falls back
    to disk rather than raising AttributeError. Should never happen
    in normal flow but the helper must not crash callers."""
    disk = SimpleNamespace(model="from-disk")
    fake_agent = SimpleNamespace()  # no cfg attribute
    with patch(
        "athena.agent.core.get_current_agent", return_value=fake_agent,
    ), patch(
        "athena.config.load_config", return_value=disk,
    ):
        assert active_cfg() is disk
