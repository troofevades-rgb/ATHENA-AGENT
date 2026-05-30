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
    # ``/status live`` used to render a Rich.Live dashboard via
    # ``ui.live_status``. That function was removed during the
    # UI cleanup — the same live data (model, profile, elapsed,
    # tokens, tool histogram) is already pinned to the bottom
    # of the Ink TUI by the StatusBar component, so a duplicate
    # dashboard added no information. ``/status`` now always
    # renders the one-shot static snapshot.
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
    # 0.3.0 Phase 2: godmode session state -- active strategy + mode
    # (system_prompt / steer) + prefill file. Operators see at-a-glance
    # whether the session is jailbroken without running /godmode list.
    active = getattr(agent, "_active_godmode", None)
    if active is not None and isinstance(active, dict):
        snapshot["godmode"] = {
            "strategy": active.get("strategy"),
            "mode": active.get("mode"),
            "applied_at": active.get("applied_at"),
        }
    prefill_file = getattr(agent.cfg, "agent_prefill_messages_file", None)
    if prefill_file:
        snapshot["godmode_prefill_file"] = prefill_file
    ui.console.print(render_status(snapshot))
    return ""
