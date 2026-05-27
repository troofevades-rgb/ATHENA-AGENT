"""Per-run state machine for ``athena train run``.

Covers state-file roundtrip, phase transitions, resume detection, and
HF-checkpoint discovery used by the SFT resume path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.transform.run_state import (
    PHASES,
    STATE_FILE_NAME,
    PhaseState,
    RunState,
    find_latest_checkpoint,
    load,
)


# ---- Fresh state -------------------------------------------------------


def test_new_default_dpo_and_export_disabled(tmp_path: Path):
    """If neither DPO nor export was opted in, both phases start as
    ``skipped`` so the runner won't loop trying to run them."""
    state = RunState.new(
        run_id="r1",
        output_dir=tmp_path,
        args={"base_model": "qwen2.5:14b"},
        dpo_enabled=False,
        export_enabled=False,
    )
    assert state.status_of("sft") == "pending"
    assert state.status_of("dpo") == "skipped"
    assert state.status_of("export") == "skipped"
    assert state.next_runnable() == "sft"


def test_new_all_phases_pending(tmp_path: Path):
    state = RunState.new(
        run_id="r1",
        output_dir=tmp_path,
        args={},
        dpo_enabled=True,
        export_enabled=True,
    )
    for name in PHASES:
        assert state.status_of(name) == "pending"
    assert state.next_runnable() == "sft"


def test_canonical_phase_order(tmp_path: Path):
    """``next_runnable`` must follow the canonical PHASES order even if
    a later phase happens to be pending while an earlier one is failed."""
    state = RunState.new(
        run_id="r1",
        output_dir=tmp_path,
        args={},
        dpo_enabled=True,
        export_enabled=True,
    )
    state.start_phase("sft")
    state.fail_phase("sft", exit_code=1)
    # Even though dpo+export are still pending, sft is the next runnable
    # because it's earlier in the topology and ``failed`` means retry.
    assert state.next_runnable() == "sft"


# ---- Transitions -------------------------------------------------------


def test_start_increments_attempts(tmp_path: Path):
    state = RunState.new(
        run_id="r1", output_dir=tmp_path, args={},
        dpo_enabled=False, export_enabled=False,
    )
    state.start_phase("sft")
    assert state.phases["sft"].attempts == 1
    state.fail_phase("sft", exit_code=1)
    state.start_phase("sft")
    assert state.phases["sft"].attempts == 2


def test_complete_sets_timestamps_and_exit_code(tmp_path: Path):
    state = RunState.new(
        run_id="r1", output_dir=tmp_path, args={},
        dpo_enabled=False, export_enabled=False,
    )
    state.start_phase("sft")
    state.complete_phase("sft", exit_code=0)
    ps = state.phases["sft"]
    assert ps.status == "completed"
    assert ps.exit_code == 0
    assert ps.started_at is not None
    assert ps.completed_at is not None


def test_fail_clears_on_restart(tmp_path: Path):
    """A new ``start_phase`` after a failure clears the prior error
    rather than letting it leak into the new attempt's record."""
    state = RunState.new(
        run_id="r1", output_dir=tmp_path, args={},
        dpo_enabled=False, export_enabled=False,
    )
    state.start_phase("sft")
    state.fail_phase("sft", exit_code=1, error="OOM at step 450")
    state.start_phase("sft")  # retry
    assert state.phases["sft"].error is None
    assert state.phases["sft"].status == "running"


def test_unknown_phase_raises(tmp_path: Path):
    state = RunState.new(
        run_id="r1", output_dir=tmp_path, args={},
        dpo_enabled=False, export_enabled=False,
    )
    with pytest.raises(KeyError):
        state.start_phase("nonexistent")


def test_is_complete_requires_at_least_one_completed(tmp_path: Path):
    """A run with everything ``skipped`` shouldn't count as complete —
    nothing actually ran."""
    state = RunState.new(
        run_id="r1", output_dir=tmp_path, args={},
        dpo_enabled=False, export_enabled=False,
    )
    state.skip_phase("sft")
    assert state.is_complete() is False

    state.start_phase("sft")
    state.complete_phase("sft")
    assert state.is_complete() is True


def test_needs_run_treats_failed_and_running_as_resumable(tmp_path: Path):
    """A run interrupted mid-phase (status still ``running``) should be
    picked up on resume the same as a ``failed`` one."""
    state = RunState.new(
        run_id="r1", output_dir=tmp_path, args={},
        dpo_enabled=True, export_enabled=True,
    )
    state.start_phase("sft")
    state.complete_phase("sft")
    state.start_phase("dpo")
    # Simulate a crash mid-DPO (no transition recorded)
    assert state.needs_run("dpo") is True
    assert state.next_runnable() == "dpo"


# ---- Roundtrip ---------------------------------------------------------


def test_save_and_load_roundtrip(tmp_path: Path):
    state = RunState.new(
        run_id="r1",
        output_dir=tmp_path,
        args={"base_model": "qwen2.5:14b", "epochs": 3},
        dpo_enabled=True,
        export_enabled=True,
    )
    state.start_phase("sft")
    state.complete_phase("sft", checkpoint=str(tmp_path / "checkpoints" / "checkpoint-450"))
    state.start_phase("dpo")
    state.fail_phase("dpo", exit_code=139, error="segfault in trl 0.9.0")
    written = state.save()
    assert written.name == STATE_FILE_NAME

    reloaded = load(tmp_path)
    assert reloaded is not None
    assert reloaded.run_id == "r1"
    assert reloaded.args == {"base_model": "qwen2.5:14b", "epochs": 3}
    assert reloaded.status_of("sft") == "completed"
    assert reloaded.phases["sft"].checkpoint and "checkpoint-450" in reloaded.phases["sft"].checkpoint
    assert reloaded.status_of("dpo") == "failed"
    assert reloaded.phases["dpo"].error == "segfault in trl 0.9.0"
    assert reloaded.status_of("export") == "pending"


def test_load_returns_none_when_no_state_file(tmp_path: Path):
    assert load(tmp_path) is None


def test_save_is_atomic_under_crash(tmp_path: Path, monkeypatch):
    """A crash mid-write must leave the prior file untouched, not
    a half-written one that downstream loads would error on."""
    state = RunState.new(
        run_id="r1", output_dir=tmp_path, args={},
        dpo_enabled=False, export_enabled=False,
    )
    state.save()
    original = (tmp_path / STATE_FILE_NAME).read_text(encoding="utf-8")

    # Force the rename step to blow up after the temp file is written.
    import athena.transform.run_state as rs

    def boom(self, target):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(Path, "replace", boom)

    state.start_phase("sft")
    with pytest.raises(OSError):
        state.save()

    # The original file is intact; no .tmp turd left behind.
    assert (tmp_path / STATE_FILE_NAME).read_text(encoding="utf-8") == original
    assert not (tmp_path / (STATE_FILE_NAME + ".tmp")).exists()


def test_load_rejects_newer_schema(tmp_path: Path):
    """Refuse to load a state file from a future athena rather than
    silently misinterpreting fields."""
    path = tmp_path / STATE_FILE_NAME
    path.write_text(
        json.dumps(
            {
                "schema_version": 999,
                "run_id": "r1",
                "output_dir": str(tmp_path),
                "args": {},
                "phases": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="schema_version"):
        load(tmp_path)


def test_state_file_is_human_readable(tmp_path: Path):
    """The point of JSON-not-pickle is debuggability — assert the file
    is indented and sorted so a human can cat it and orient themselves."""
    state = RunState.new(
        run_id="r1", output_dir=tmp_path, args={},
        dpo_enabled=False, export_enabled=False,
    )
    state.save()
    raw = (tmp_path / STATE_FILE_NAME).read_text(encoding="utf-8")
    assert "\n  " in raw  # indented
    # Keys appear in alpha order — args before phases before run_id.
    assert raw.index('"args"') < raw.index('"phases"') < raw.index('"run_id"')


# ---- Checkpoint discovery ----------------------------------------------


def _mk_ckpt(parent: Path, step: int, valid: bool = True) -> Path:
    d = parent / f"checkpoint-{step}"
    d.mkdir(parents=True)
    if valid:
        (d / "trainer_state.json").write_text("{}", encoding="utf-8")
    return d


def test_find_latest_checkpoint_returns_highest(tmp_path: Path):
    _mk_ckpt(tmp_path, 100)
    _mk_ckpt(tmp_path, 500)
    _mk_ckpt(tmp_path, 250)
    result = find_latest_checkpoint(tmp_path)
    assert result is not None
    assert result.name == "checkpoint-500"


def test_find_latest_checkpoint_skips_invalid(tmp_path: Path):
    """A checkpoint dir without ``trainer_state.json`` is treated as
    half-written; we should pick the next valid one down rather than
    resume from corrupted state."""
    _mk_ckpt(tmp_path, 100, valid=True)
    _mk_ckpt(tmp_path, 500, valid=False)  # crashed mid-save
    result = find_latest_checkpoint(tmp_path)
    assert result is not None
    assert result.name == "checkpoint-100"


def test_find_latest_checkpoint_none_when_empty(tmp_path: Path):
    assert find_latest_checkpoint(tmp_path) is None


def test_find_latest_checkpoint_none_when_dir_missing(tmp_path: Path):
    assert find_latest_checkpoint(tmp_path / "does-not-exist") is None


def test_find_latest_checkpoint_ignores_nonconforming_dirs(tmp_path: Path):
    """Dirs that aren't named ``checkpoint-N`` shouldn't trip the regex."""
    _mk_ckpt(tmp_path, 100)
    other = tmp_path / "final"
    other.mkdir()
    (other / "trainer_state.json").write_text("{}", encoding="utf-8")
    result = find_latest_checkpoint(tmp_path)
    assert result is not None
    assert result.name == "checkpoint-100"


# ---- Summary printing --------------------------------------------------


def test_summary_lines_contains_all_phases(tmp_path: Path):
    state = RunState.new(
        run_id="qwen3-30b-athena-1",
        output_dir=tmp_path,
        args={},
        dpo_enabled=True,
        export_enabled=True,
    )
    state.start_phase("sft")
    state.complete_phase("sft", checkpoint=str(tmp_path / "checkpoint-450"))
    state.start_phase("dpo")
    state.fail_phase("dpo", exit_code=1, error="trl version mismatch")
    lines = "\n".join(state.summary_lines())
    assert "qwen3-30b-athena-1" in lines
    assert "sft" in lines and "completed" in lines
    assert "dpo" in lines and "failed" in lines
    assert "export" in lines and "pending" in lines
    assert "trl version mismatch" in lines


# ---- invalidate_downstream --------------------------------------------


def test_invalidate_downstream_resets_completed(tmp_path: Path):
    """If sft succeeds on resume after a prior failure, dpo+export
    (which may have been completed via the SFT-only path) need to
    re-run on top of the new adapter."""
    state = RunState.new(
        run_id="r1", output_dir=tmp_path, args={},
        dpo_enabled=True, export_enabled=True,
    )
    state.start_phase("sft")
    state.complete_phase("sft")
    state.start_phase("dpo")
    state.complete_phase("dpo")
    state.start_phase("export")
    state.complete_phase("export")

    reset = state.invalidate_downstream("sft")
    assert set(reset) == {"dpo", "export"}
    assert state.status_of("dpo") == "pending"
    assert state.status_of("export") == "pending"
    # sft itself is untouched.
    assert state.status_of("sft") == "completed"


def test_invalidate_downstream_leaves_skipped_alone(tmp_path: Path):
    """The user opted out of DPO. A late SFT change should NOT
    silently turn DPO back on."""
    state = RunState.new(
        run_id="r1", output_dir=tmp_path, args={},
        dpo_enabled=False, export_enabled=True,
    )
    state.start_phase("sft")
    state.complete_phase("sft")
    state.start_phase("export")
    state.complete_phase("export")
    reset = state.invalidate_downstream("sft")
    assert reset == ["export"]
    assert state.status_of("dpo") == "skipped"


def test_invalidate_downstream_keeps_attempts(tmp_path: Path):
    """Phases reset by invalidation should keep their cumulative attempt
    count — the resetting was caused by upstream, not a fresh restart."""
    state = RunState.new(
        run_id="r1", output_dir=tmp_path, args={},
        dpo_enabled=True, export_enabled=False,
    )
    state.start_phase("sft")
    state.complete_phase("sft")
    state.start_phase("dpo")
    state.fail_phase("dpo", exit_code=1)
    state.start_phase("dpo")
    state.complete_phase("dpo")
    # dpo has 2 attempts at this point
    state.invalidate_downstream("sft")
    assert state.phases["dpo"].attempts == 2


def test_invalidate_downstream_unknown_phase_raises(tmp_path: Path):
    state = RunState.new(
        run_id="r1", output_dir=tmp_path, args={},
        dpo_enabled=False, export_enabled=False,
    )
    with pytest.raises(KeyError):
        state.invalidate_downstream("nope")
