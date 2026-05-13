"""Persistent curator state at ``<skills_root>/.curator_state``.

Tracks when the curator last ran, how many times it has run, and whether
the user has paused it. The file is JSON for readability — the curator
state is something users may want to inspect with ``cat``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


_STATE_FILENAME = ".curator_state"


@dataclass
class State:
    last_run_at: datetime | None = None
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


def read_state(skills_root: Path) -> State:
    """Return the persisted state, or a default ``State()`` when the file is
    missing or malformed."""
    p = _state_path(skills_root)
    if not p.exists():
        return State()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return State()
    if not isinstance(raw, dict):
        return State()
    return State(
        last_run_at=_coerce_dt(raw.get("last_run_at")),
        run_count=int(raw.get("run_count") or 0),
        paused=bool(raw.get("paused") or False),
    )


def write_state(skills_root: Path, state: State) -> None:
    """Atomically write ``state`` to disk. Parent directory is created if
    missing — the curator can run before the user has any skills."""
    skills_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_run_at": state.last_run_at.isoformat() if state.last_run_at else None,
        "run_count": state.run_count,
        "paused": state.paused,
    }
    p = _state_path(skills_root)
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
