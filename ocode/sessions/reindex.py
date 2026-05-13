"""Rebuild ``sessions.db`` from the JSONL files on disk.

Workflow:

1. Back up the existing ``sessions.db`` to ``sessions.db.bak`` (if any).
2. Drop and recreate the schema in place.
3. For each ``<id>.jsonl``:
   - Read the sidecar ``<id>.meta.json`` (or construct minimal meta).
   - Insert a session row.
   - Walk the JSONL, insert one turn per message.
4. On failure mid-flight, restore from ``.bak`` so the user is never left
   with an empty index.

Returns a dict with counts and a list of files that couldn't be processed
so the CLI can show a summary.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import jsonl, sqlite_index
from .store import _flatten_content


logger = logging.getLogger(__name__)


def _backup_db(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    bak = db_path.with_suffix(db_path.suffix + ".bak")
    shutil.copy2(db_path, bak)
    return bak


def _restore_db(bak: Path, db_path: Path) -> None:
    if bak.exists():
        shutil.copy2(bak, db_path)


def _load_meta(jsonl_path: Path) -> dict[str, Any]:
    """Read the sidecar meta file or construct a minimal one from the JSONL."""
    meta_path = jsonl_path.with_suffix(".meta.json")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    else:
        meta = {}

    meta.setdefault("session_id", jsonl_path.stem)
    meta.setdefault("profile", "default")
    meta.setdefault("model", "unknown")
    meta.setdefault("provider", "unknown")
    if "started_at" not in meta or not meta["started_at"]:
        mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime, tz=timezone.utc)
        meta["started_at"] = mtime.isoformat()
    return meta


def reindex(profile_dir: Path) -> dict[str, Any]:
    """Rebuild the session index for ``profile_dir``.

    Returns a summary dict::

        {
          "sessions": <int>,
          "turns": <int>,
          "skipped_files": [<Path>, ...],
          "duration_s": <float>,
        }
    """
    sessions_dir = profile_dir / "sessions"
    db_path = profile_dir / "sessions.db"
    start = time.time()

    if not sessions_dir.exists():
        return {"sessions": 0, "turns": 0, "skipped_files": [], "duration_s": 0.0}

    bak = _backup_db(db_path)
    if db_path.exists():
        db_path.unlink()

    sessions_count = 0
    turns_count = 0
    skipped: list[Path] = []

    db = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        sqlite_index.init_schema(db)
        for jsonl_path in sorted(sessions_dir.glob("*.jsonl")):
            try:
                meta = _load_meta(jsonl_path)
                sqlite_index.insert_session(db, meta)
                sessions_count += 1
                turn_index = 0
                for msg in jsonl.read_jsonl(jsonl_path):
                    if not isinstance(msg, dict):
                        continue
                    role = str(msg.get("role") or "user")
                    content = _flatten_content(msg)
                    tool_name = msg.get("name") if role == "tool" else None
                    timestamp = msg.get("timestamp") or meta["started_at"]
                    sqlite_index.insert_turn(
                        db, meta["session_id"], turn_index,
                        role, content, tool_name, timestamp,
                    )
                    turn_index += 1
                    turns_count += 1
            except Exception as e:
                logger.warning("reindex: skipping %s (%s)", jsonl_path, e)
                skipped.append(jsonl_path)
    except Exception:
        db.close()
        if bak is not None:
            _restore_db(bak, db_path)
        raise
    finally:
        db.close()

    duration = time.time() - start
    return {
        "sessions": sessions_count,
        "turns": turns_count,
        "skipped_files": skipped,
        "duration_s": duration,
    }
