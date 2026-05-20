"""End-to-end checkpoint+rollback cycle (T3-03.10).

Doesn't spin up a real Agent (that would pull credentials and a
provider). Instead drives the wedge as a user would:

1. Build a CheckpointManager rooted in tmp_path.
2. Bind it to the ContextVar so file_ops's Write tool tracks
   modifications back to it.
3. Run Write through the actual tool registry to mutate a file
   in the workspace.
4. Snapshot via /checkpoint slash command.
5. Mutate again.
6. Rollback via /rollback-to slash command.
7. Verify: file restored, session log truncated, marker appended,
   in-memory transcript reload reflects the truncation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from athena.agent.checkpoints import (
    CheckpointManager,
    set_active_checkpoint_manager,
)
from athena.commands import get_command
from athena.safety.snapshots import SnapshotStore


@dataclass
class _StubAgent:
    """Just enough of Agent's surface for the slash commands."""

    checkpoint_manager: Any
    messages: list[dict[str, Any]] = field(default_factory=list)


@pytest.fixture
def setup(tmp_path: Path):
    """Compose a workspace, profile dir, session JSONL, manager, and
    bound ContextVar. Yields the tuple; resets the ContextVar after."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    profile = tmp_path / "profile"
    (profile / "sessions").mkdir(parents=True)

    session_id = "integration-session"
    session_log = profile / "sessions" / f"{session_id}.jsonl"
    # Seed with the system prompt + a user message — what Agent
    # would have at this point.
    session_log.write_text(
        json.dumps({"role": "system", "content": "you are athena"})
        + "\n"
        + json.dumps({"role": "user", "content": "start"})
        + "\n",
        encoding="utf-8",
    )

    snapshot_store = SnapshotStore(
        root=tmp_path / "fs_snapshots",
        relative_to=tmp_path,
    )
    mgr = CheckpointManager(
        session_id=session_id,
        session_log_path=session_log,
        checkpoint_dir=tmp_path / "checkpoints",
        snapshot_store=snapshot_store,
        profile_dir=profile,
        workspace=workspace,
    )
    agent = _StubAgent(checkpoint_manager=mgr)
    set_active_checkpoint_manager(mgr)
    try:
        yield workspace, mgr, agent, session_log
    finally:
        set_active_checkpoint_manager(None)


def test_full_rollback_cycle(setup, monkeypatch) -> None:
    workspace, mgr, agent, session_log = setup

    # Bind file_ops to the workspace so its _resolve treats absolute
    # paths under the workspace as in-bounds.
    from athena.tools import file_ops

    file_ops.set_workspace(workspace, max_read=1_000_000)

    # ---- Mutate a file via the real Write tool ----
    data_path = workspace / "data.txt"
    data_path.write_text("version A", encoding="utf-8")
    # Pre-checkpoint snapshot of the file. The Write tool calls
    # track_modified_file for us via the ContextVar; the manager
    # picks up the path.
    result = file_ops.Write(file_path=str(data_path), content="version A")
    assert "data.txt" in result
    assert data_path.resolve() in mgr._tracked_modified_files

    # ---- /checkpoint label="start" ----
    cmd_checkpoint = get_command("checkpoint")
    assert cmd_checkpoint is not None
    cmd_checkpoint(agent, "start")
    cps = mgr.list()
    assert any(c.label == "start" for c in cps)
    cp_start = next(c for c in cps if c.label == "start")
    assert cp_start.file_snapshot_id is not None

    # ---- Mutate again (a second turn would do this) ----
    file_ops.Write(file_path=str(data_path), content="version B")
    assert data_path.read_text(encoding="utf-8") == "version B"

    # ---- Add some session messages ----
    with open(session_log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"role": "assistant", "content": "did edit"}) + "\n")
        f.write(json.dumps({"role": "user", "content": "more"}) + "\n")
    assert mgr._count_session_messages() == 4

    # ---- /rollback-to start ----
    cmd_rollback = get_command("rollback-to")
    assert cmd_rollback is not None
    cmd_rollback(agent, "start")

    # File restored
    assert data_path.read_text(encoding="utf-8") == "version A"

    # Session log: truncated to 2 messages + the synthetic marker = 3
    lines = session_log.read_text(encoding="utf-8").splitlines()
    non_blank = [ln for ln in lines if ln.strip()]
    assert len(non_blank) == 3
    last = json.loads(non_blank[-1])
    assert last["role"] == "system"
    assert "rolled back" in last["content"].lower()

    # In-memory transcript reloaded from disk
    assert len(agent.messages) == 3
    assert agent.messages[-1]["role"] == "system"
    assert "rolled back" in agent.messages[-1]["content"].lower()

    # ---- /checkpoints list shows both `start` and `pre-rollback-of-...` ----
    cmd_list = get_command("checkpoints")
    assert cmd_list is not None
    cmd_list(agent, "")
    all_labels = {c.label for c in mgr.list()}
    assert "start" in all_labels
    assert any(lbl.startswith("pre-rollback-") for lbl in all_labels)

    # ---- /checkpoints purge removes only pre-rollback-* ----
    cmd_list(agent, "purge")
    remaining = {c.label for c in mgr.list()}
    assert "start" in remaining
    assert not any(lbl.startswith("pre-rollback-") for lbl in remaining)


def test_slash_command_without_manager_errors_cleanly() -> None:
    """An Agent without a checkpoint_manager (forks, profile-less)
    must surface a clear error rather than crashing."""
    agent = _StubAgent(checkpoint_manager=None)
    cmd_checkpoint = get_command("checkpoint")
    cmd_rollback = get_command("rollback-to")
    cmd_list = get_command("checkpoints")
    # None of these should raise.
    cmd_checkpoint(agent, "x")
    cmd_rollback(agent, "x")
    cmd_list(agent, "")


def test_rollback_to_unknown_label_surfaces_error(setup) -> None:
    _ws, _mgr, agent, _log = setup
    # No checkpoints yet — rollback to an unknown label must not raise.
    cmd_rollback = get_command("rollback-to")
    cmd_rollback(agent, "nonexistent")
    # No pre-rollback was created since the rollback never started.
    assert agent.checkpoint_manager.list() == []
