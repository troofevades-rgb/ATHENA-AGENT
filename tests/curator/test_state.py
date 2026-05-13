"""Tests for ocode.curator.state."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ocode.curator.state import State, read_state, write_state


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
