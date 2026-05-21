"""Vision provenance hash-log (T4-01.2).

Every image athena's ``vision_analyze`` tool *reads* — describe,
EXIF, ELA, pHash, all of them — gets a JSONL audit row written
here. The row carries:

  - the path that was opened
  - SHA-256 of the file bytes (provenance fingerprint)
  - byte size
  - the analysis mode that triggered the read
  - the ISO-8601 timestamp

The bytes themselves are NOT stored — same call as
:mod:`athena.computer.audit`: the hash gives a third party the
ability to ask "is this the same file I had a copy of", but
storing the bytes would grow the log unboundedly.

The log lives under ``<profile_dir>/vision_audit.jsonl``,
co-located with the rest of the per-profile state. Concurrent
appends are serialised via a per-instance lock so a future
multi-threaded caller (eg. a batch describe over a folder)
doesn't interleave half-lines.

The format intentionally mirrors :mod:`athena.computer.audit`
so the existing diff / query tooling already in the repo can
be extended uniformly.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


_AUDIT_FILENAME = "vision_audit.jsonl"


def sha256_file(path: Path | str, *, chunk_size: int = 1 << 20) -> str:
    """Hex SHA-256 of the file at ``path``, streamed in 1 MB
    chunks so a 4K screenshot or a multi-MB photo doesn't pull
    the whole file into RAM.

    Raises FileNotFoundError if the path doesn't exist (same as
    ``open``) — callers above this layer translate that to the
    appropriate user-facing error string.
    """
    h = hashlib.sha256()
    p = Path(path)
    with open(p, "rb") as f:
        while True:
            buf = f.read(chunk_size)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _now_iso() -> str:
    """ISO-8601 UTC with microsecond precision and trailing 'Z' —
    matches :mod:`athena.computer.audit`."""
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


@dataclasses.dataclass
class HashLogEntry:
    """One row of the vision hash-log."""

    ts: str
    mode: str
    path: str
    sha256: str
    bytes: int
    extra: dict | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "ts": self.ts,
            "mode": self.mode,
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
        }
        if self.extra:
            d["extra"] = self.extra
        return d


def audit_path(profile_dir: Path | str) -> Path:
    """Canonical hash-log path for a given profile directory."""
    return Path(profile_dir) / _AUDIT_FILENAME


class HashLogger:
    """Append-only JSONL hash-log over images vision_analyze touches.

    Construction is cheap — no I/O until the first :meth:`log`
    call. The parent directory is created lazily so a brand-new
    profile doesn't trip on a missing dir.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()

    def log(
        self,
        *,
        mode: str,
        path: Path | str,
        sha256: str,
        size_bytes: int,
        extra: dict | None = None,
    ) -> HashLogEntry:
        """Append one row. Returns the entry so callers can echo
        it back to the model (the ``vision_analyze`` tool surfaces
        ``sha256`` + ``bytes`` in its result payload)."""
        entry = HashLogEntry(
            ts=_now_iso(),
            mode=mode,
            path=str(path),
            sha256=sha256,
            bytes=int(size_bytes),
            extra=extra,
        )
        line = json.dumps(entry.to_dict(), separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        logger.debug("vision audit: %s", line)
        return entry

    def tail(self, limit: int = 100) -> list[HashLogEntry]:
        """Read the last ``limit`` entries — for status / debug.
        Returns [] when the file doesn't exist yet."""
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        out: list[HashLogEntry] = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("malformed vision audit line: %r", line[:120])
                continue
            out.append(
                HashLogEntry(
                    ts=str(d.get("ts", "")),
                    mode=str(d.get("mode", "")),
                    path=str(d.get("path", "")),
                    sha256=str(d.get("sha256", "")),
                    bytes=int(d.get("bytes", 0)),
                    extra=d.get("extra") or None,
                )
            )
        return out
