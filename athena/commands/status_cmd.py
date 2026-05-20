"""``/status`` — render the session snapshot.

``--live`` (or bare ``live``) opens the Rich dashboard view; the
default mode prints the text snapshot used by ``athena status``
out-of-process. Both paths funnel through
``athena.cli.status.render_status`` so the formatting is
consistent across surfaces.

The text path grafts T2-02 rate-limit state and T2-03 retry/abort
counters onto the snapshot when the active provider exposes the
``get_rate_limit_state`` / ``get_retry_counts`` accessors.
"""

from __future__ import annotations

from .. import ui
from . import command


@command("status")
def cmd_status(agent, arg: str = "") -> str:
    if arg.strip() in ("live", "--live"):
        ui.live_status(agent)
        return ""
    from ..cli.status import render_status

    snapshot = agent.stats.to_snapshot(
        session_id=agent.session_id,
        model=agent.model,
        provider=getattr(agent.provider, "name", "?"),
        profile=(agent.cfg.profile or "default"),
        cache_strategy=getattr(agent.cfg, "cache_strategy", None),
        prompt_cache_ttl=getattr(agent.cfg, "prompt_cache_ttl", None),
    )
    # T2-02: rate-limit state per credential.
    rl_getter = getattr(agent.provider, "get_rate_limit_state", None)
    if callable(rl_getter):
        snapshot["rate_limits"] = {
            cred_id: tracker.format() for cred_id, tracker in rl_getter().items()
        }
    # T2-03.9: per-session retry / abort counters.
    rc_getter = getattr(agent.provider, "get_retry_counts", None)
    if callable(rc_getter):
        snapshot["retry_counts"] = {snapshot["provider"]: rc_getter()}
    ui.console.print(render_status(snapshot))
    return ""
