"""``/checkpoint``, ``/rollback-to``, ``/checkpoints`` slash commands (T3-03.7).

The Agent owns a :class:`CheckpointManager` (built in
``Agent.__init__`` for foreground sessions). These handlers
delegate; they don't reach into snapshot/skill/memory mechanics
themselves.

Slash commands return a string that the REPL renders directly
(per the convention in ``athena/__main__.py:_handle_slash``).
None of these commands inject the result as a new user turn
because that would feed checkpoint chatter into the model.
"""

from __future__ import annotations

from typing import Any

from .. import ui
from ..agent.checkpoints import CheckpointNotFound, InFlightToolCallError
from . import command

# Per-file conflict prompting is intentionally not wired in T3-03.
# The safety net is the auto-created pre-rollback checkpoint:
# CheckpointManager.rollback_to snapshots the current state BEFORE
# overwriting anything, so any externally-modified files captured
# in that pre-rollback snapshot can be recovered by rolling forward
# again. SnapshotStore.restore is all-or-nothing today; a richer
# per-file diff/prompt flow is a follow-up.


@command("checkpoint")
def cmd_checkpoint(agent: Any, arg: str = "") -> str:
    """Create a checkpoint. Usage: /checkpoint [label]"""
    mgr = getattr(agent, "checkpoint_manager", None)
    if mgr is None:
        ui.error("checkpoint manager not available in this session")
        return ""
    label = arg.strip() or None
    try:
        cp = mgr.create(label=label)
    except Exception as e:  # noqa: BLE001
        ui.error(f"checkpoint failed: {e}")
        return ""
    ui.info(f"checkpoint created: {cp.id} (label={cp.label!r})")
    return ""


@command("rollback-to")
def cmd_rollback_to(agent: Any, arg: str = "") -> str:
    """Rollback to a checkpoint by label or id.
    Usage: /rollback-to <label-or-id>"""
    mgr = getattr(agent, "checkpoint_manager", None)
    if mgr is None:
        ui.error("checkpoint manager not available in this session")
        return ""
    label_or_id = arg.strip()
    if not label_or_id:
        ui.error("usage: /rollback-to <label-or-id>")
        return ""
    try:
        cp = mgr.rollback_to(label_or_id, on_file_conflict=None)
    except InFlightToolCallError as e:
        ui.error(str(e))
        return ""
    except CheckpointNotFound as e:
        ui.error(str(e))
        return ""
    except Exception as e:  # noqa: BLE001
        ui.error(f"rollback failed: {e}")
        return ""
    ui.info(f"rolled back to {cp.label!r} ({cp.id}). pre-rollback state captured for undo.")
    # Reload the agent's in-memory message list from the (now-truncated)
    # session log so the next provider call sees the rolled-back state.
    _reload_agent_messages(agent)
    return ""


@command("checkpoints")
def cmd_checkpoints(agent: Any, arg: str = "") -> str:
    """List checkpoints, or `/checkpoints purge` to drop auto-created
    pre-rollback entries.
    Usage: /checkpoints [purge]"""
    mgr = getattr(agent, "checkpoint_manager", None)
    if mgr is None:
        ui.error("checkpoint manager not available in this session")
        return ""
    sub = arg.strip().lower()
    if sub == "purge":
        n = mgr.purge_pre_rollback()
        ui.info(f"purged {n} pre-rollback checkpoint(s)")
        return ""
    cps = mgr.list()
    if not cps:
        ui.info("no checkpoints in this session yet")
        return ""
    for cp in cps:
        note = f"  ({cp.notes})" if cp.notes else ""
        ui.info(f"  {cp.id}  {cp.created_at}  {cp.label}{note}")
    return ""


def _reload_agent_messages(agent: Any) -> None:
    """After a rollback truncates the session log, re-sync
    ``agent.messages`` (the in-memory transcript fed to the provider)
    from the now-shortened JSONL plus the synthetic rollback marker.

    Best-effort: a reload failure leaves the in-memory list as-is,
    which will diverge from the on-disk log until the next session
    resume. We warn loudly so the user knows to restart the session
    if the in-memory state matters to them.
    """
    import json

    log_path = agent.checkpoint_manager.session_log_path
    if not log_path.exists():
        return
    try:
        new_messages: list[dict[str, Any]] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                new_messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        # Keep the system prompt if the rebuilt list doesn't already
        # have one — Agent built it at __init__ from cfg.
        if not new_messages or new_messages[0].get("role") != "system":
            existing_system = next((m for m in agent.messages if m.get("role") == "system"), None)
            if existing_system is not None:
                new_messages.insert(0, existing_system)
        agent.messages = new_messages
    except Exception as e:  # noqa: BLE001
        ui.warn(
            f"rollback succeeded on disk but the in-memory transcript "
            f"failed to reload ({e}). Exit and resume the session to "
            "fully resync."
        )
