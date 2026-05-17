"""Tests for athena.curator.state."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from athena.curator.state import State, mark_summary_shown, read_state, write_state


def test_default_state_when_file_missing(tmp_path: Path) -> None:
    s = read_state(tmp_path / "missing")
    assert s == State()
    assert s.last_run_at is None
    assert s.run_count == 0
    assert s.paused is False


def test_state_round_trips(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    state = State(
        last_run_at=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        run_count=5,
        paused=False,
    )
    write_state(skills_root, state)
    loaded = read_state(skills_root)
    assert loaded.last_run_at == state.last_run_at
    assert loaded.run_count == 5
    assert loaded.paused is False


def test_paused_persists(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    write_state(skills_root, State(paused=True))
    assert read_state(skills_root).paused is True


def test_corrupt_state_falls_back_to_default(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    (skills_root / ".curator_state").write_text("not json at all", encoding="utf-8")
    assert read_state(skills_root) == State()


def test_state_creates_parent_dir(tmp_path: Path) -> None:
    skills_root = tmp_path / "nested" / "deeper" / "skills"
    write_state(skills_root, State(run_count=1))
    assert (skills_root / ".curator_state").exists()


def test_extended_fields_round_trip(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    state = State(
        last_run_at=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        last_run_duration_seconds=42.5,
        last_run_summary="3 keep, 2 consolidate",
        last_run_summary_shown_at=datetime(2026, 4, 1, 13, 0, tzinfo=timezone.utc),
        last_report_path="/tmp/curator/20260401/REPORT.md",
        run_count=7,
        paused=False,
    )
    write_state(skills_root, state)
    loaded = read_state(skills_root)
    assert loaded == state


def test_legacy_state_file_missing_new_fields_still_loads(tmp_path: Path) -> None:
    """A state file written by an older athena version (no extended fields)
    must still load — pre-retrofit users shouldn't lose run_count/paused."""
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    legacy_payload = {
        "last_run_at": "2026-03-15T08:00:00+00:00",
        "run_count": 12,
        "paused": True,
    }
    (skills_root / ".curator_state").write_text(
        json.dumps(legacy_payload), encoding="utf-8",
    )
    loaded = read_state(skills_root)
    assert loaded.last_run_at == datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
    assert loaded.run_count == 12
    assert loaded.paused is True
    # New fields default to None / 0.
    assert loaded.last_run_duration_seconds is None
    assert loaded.last_run_summary is None


def test_mark_summary_shown_only_touches_shown_at(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    base = State(
        last_run_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        last_run_summary="3 keep",
        run_count=5,
        paused=False,
    )
    write_state(skills_root, base)
    mark_summary_shown(skills_root)
    loaded = read_state(skills_root)
    assert loaded.last_run_summary_shown_at is not None
    assert loaded.last_run_at == base.last_run_at
    assert loaded.last_run_summary == "3 keep"
    assert loaded.run_count == 5


def test_write_is_atomic_no_partial_files_left(tmp_path: Path) -> None:
    """Successful writes don't leave .tmp scratch files behind."""
    skills_root = tmp_path / "skills"
    write_state(skills_root, State(run_count=1))
    leftovers = list(skills_root.glob(".curator_state_*.tmp"))
    assert leftovers == []
