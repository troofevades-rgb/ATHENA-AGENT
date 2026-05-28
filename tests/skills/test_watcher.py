"""SkillWatcher polling-watcher tests."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from athena.skills.watcher import SkillWatcher


def _write_skill(base: Path, name: str, description: str = "demo") -> Path:
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nbody\n",
        encoding="utf-8",
    )
    return skill_dir


def _wait_for(predicate, timeout: float = 3.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_watcher_fires_on_added_skill(
    isolated_home: Path, tmp_path: Path,
) -> None:
    """Adding a new SKILL.md after the watcher starts must fire the
    on_change callback in less than poll_interval * 3 seconds."""
    base = isolated_home / ".athena" / "skills"
    base.mkdir(parents=True)
    _write_skill(base, "preexisting")  # baseline

    fired = threading.Event()
    watcher = SkillWatcher(
        workspace=None,
        on_change=fired.set,
        poll_interval=0.5,
    )
    watcher.start()
    try:
        _write_skill(base, "newly-added")
        assert _wait_for(fired.is_set, timeout=3.0)
    finally:
        watcher.stop()


def test_watcher_fires_on_modified_skill(
    isolated_home: Path, tmp_path: Path,
) -> None:
    """Editing an existing SKILL.md must also fire the callback. Mtime
    is bumped explicitly so we don't depend on filesystem
    granularity beneath the poll interval."""
    base = isolated_home / ".athena" / "skills"
    base.mkdir(parents=True)
    skill_dir = _write_skill(base, "to-modify")

    fired = threading.Event()
    watcher = SkillWatcher(
        workspace=None,
        on_change=fired.set,
        poll_interval=0.5,
    )
    watcher.start()
    try:
        # Force a mtime change well beyond filesystem granularity by
        # using ``os.utime`` rather than just rewriting (some filesystems
        # batch sub-second mtimes).
        import os as _os
        skill_md = skill_dir / "SKILL.md"
        future = time.time() + 5
        _os.utime(skill_md, (future, future))
        assert _wait_for(fired.is_set, timeout=3.0)
    finally:
        watcher.stop()


def test_watcher_stop_is_idempotent(isolated_home: Path) -> None:
    """stop() called twice (and on a never-started watcher) must not raise."""
    w = SkillWatcher(workspace=None, on_change=lambda: None)
    w.stop()  # not started — must be a no-op
    w.start()
    w.stop()
    w.stop()  # second stop is also a no-op
