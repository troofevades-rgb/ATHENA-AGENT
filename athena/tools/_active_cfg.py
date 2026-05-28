"""Resolve the Config the active session is actually running with.

ATHENA.md / CLAUDE.md document the convention:

  Tools should read the LIVE agent's cfg via ``get_current_agent()``
  first and fall back to disk only when no agent is bound.

Several tools were silently violating that convention by calling
``load_config()`` directly. Session-scoped mutations (``/allowlist add``,
sandbox toggles, recall-mode flips, etc.) then became invisible to those
tools mid-session because they kept reading the on-disk snapshot.

This module centralises the lookup so individual tools can use a single
import and the fallback behaviour is consistent (and testable in one place).
"""

from __future__ import annotations

from typing import Any


def active_cfg() -> Any:
    """Return the Config bound to the current agent, or the on-disk
    Config when no agent is active.

    Lazy imports: the agent module pulls in providers + sessions which
    not every tool wants at module load time.
    """
    try:
        from ..agent.core import get_current_agent
    except ImportError:
        agent = None
    else:
        agent = get_current_agent()
    if agent is not None:
        cfg = getattr(agent, "cfg", None)
        if cfg is not None:
            return cfg
    from ..config import load_config
    return load_config()
