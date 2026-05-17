"""Persistent curator state at ``<skills_root>/.curator_state``.

Tracks when the curator last ran, how long the run took, a brief
summary, when the user last saw that summary, the report path, the run
count, and whether the user has paused it. The file is JSON so users
can inspect it with ``cat``; writes are atomic (temp + rename) so a
crash mid-write never leaves a half-written record.

Mirrors Hermes Agent's ``agent/curator.py`` state shape so the same
``athena curator status`` UX (last run summary, "show once per launch"
gating, report path quick-jump) lights up.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


_STATE_FILENAME = ".curator_state"


@dataclass
class State:
    last_run_at: datetime | None = None
    last_run_duration_seconds: float | None = None
    last_run_summary: str | None = None
    last_run_summary_shown_at: datetime | None = None
    last_report_path: str | None = None
    run_count: int = 0
    paused: bool = False


def _state_path(skills_root: Path) -> Path:
    return skills_root / _STATE_FILENAME


def _coerce_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    s = value.rstrip("Z")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def read_state(skills_root: Path) -> State:
    """Return the persisted state, or a default ``State()`` when the file is
    missing or malformed.

    Tolerates older state files written before the extended fields were
    added — missing keys fall back to ``State()`` defaults.
    """
    p = _state_path(skills_root)
    if not p.exists():
        return State()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return State()
    if not isinstance(raw, dict):
        return State()
    duration = raw.get("last_run_duration_seconds")
    return State(
        last_run_at=_coerce_dt(raw.get("last_run_at")),
        last_run_duration_seconds=float(duration) if duration is not None else None,
        last_run_summary=(raw.get("last_run_summary") or None),
        last_run_summary_shown_at=_coerce_dt(raw.get("last_run_summary_shown_at")),
        last_report_path=(raw.get("last_report_path") or None),
        run_count=int(raw.get("run_count") or 0),
        paused=bool(raw.get("paused") or False),
    )


def write_state(skills_root: Path, state: State) -> None:
    """Atomically write ``state`` to disk.

    Atomic via temp-file + ``os.replace`` so a crash mid-write doesn't
    leave the JSON half-formed. Mirrors Hermes ``save_state`` —
    important because the state file is read on every curator-status
    check and a torn write would degrade the entire CLI.
    """
    skills_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_run_at": _iso(state.last_run_at),
        "last_run_duration_seconds": state.last_run_duration_seconds,
        "last_run_summary": state.last_run_summary,
        "last_run_summary_shown_at": _iso(state.last_run_summary_shown_at),
        "last_report_path": state.last_report_path,
        "run_count": state.run_count,
        "paused": state.paused,
    }
    target = _state_path(skills_root)
    fd, tmp = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=".curator_state_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def mark_summary_shown(skills_root: Path) -> None:
    """Stamp ``last_run_summary_shown_at = now`` without disturbing the
    rest of the state. Called by the CLI status helper after it prints
    the summary so subsequent prompts in the same session don't repeat it.
    """
    current = read_state(skills_root)
    current.last_run_summary_shown_at = datetime.now(timezone.utc)
    write_state(skills_root, current)
