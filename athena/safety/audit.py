"""Append-only JSONL audit log of agent-driven mutations.

Forensic record: one line per mutation, monthly rollover. Every
field is required so a reviewer can answer "who, when, what, from
where" without cross-referencing another log. Reads are by humans,
not by the agent — the log is write-only from athena's perspective.

Layout::

    ~/.athena/audit/
      mutations-2026-05.jsonl
      mutations-2026-06.jsonl
      ...

Format (compact, one JSON object per line — newline-delimited)::

    {"timestamp":"...","write_origin":"curator","session_id":"...",
     "parent_session_id":"...","tool_name":"skill_manage",
     "tool_call_id":"call-7","path":"/...","snapshot_id":"...",
     "sha_before":"...","sha_after":"...","byte_delta":42}

Concurrency: a single :class:`threading.Lock` serialises all
appends; writes are short and the contention is negligible at our
scale. Cross-process concurrency is not addressed — athena assumes
one writer per profile. A multi-process layout would need
``flock`` / atomic rename, deferred until we actually have that
problem.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class MutationRecord:
    timestamp: str
    write_origin: str
    session_id: str | None
    parent_session_id: str | None
    tool_name: str
    tool_call_id: str
    path: str
    snapshot_id: str | None
    sha_before: str | None
    sha_after: str | None
    byte_delta: int


class MutationAuditLog:
    """Thread-safe append-only JSONL log under ``audit_dir``."""

    def __init__(self, audit_dir: Path) -> None:
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _current_path(self) -> Path:
        ym = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
        return self.audit_dir / f"mutations-{ym}.jsonl"

    def append(self, record: MutationRecord) -> None:
        # Compact one-line JSON so a reviewer can `wc -l` to count
        # mutations, `grep` to scope by path, and `jq` to project.
        line = json.dumps(
            dataclasses.asdict(record),
            separators=(",", ":"),
            ensure_ascii=False,
        )
        with self._lock:
            path = self._current_path()
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")


def sha_of_file(path: Path) -> str | None:
    """sha256 of file bytes, ``None`` if path is a directory or
    doesn't exist. Used to populate ``sha_before`` / ``sha_after``
    so a reviewer can verify the snapshot captures the actual
    pre/post state."""
    path = Path(path)
    try:
        if not path.exists() or path.is_dir():
            return None
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()
    except OSError:
        logger.debug("sha_of_file failed: %s", path, exc_info=True)
        return None


def now_iso() -> str:
    """ISO-8601 UTC timestamp suitable for the audit log."""
    return dt.datetime.now(dt.timezone.utc).isoformat()
