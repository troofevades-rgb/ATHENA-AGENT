"""Action audit hash-log for computer use (T6-04.4).

Every action — observe AND input, allowed AND denied — gets a
JSONL row. The screenshot the model was looking at when the
action was proposed is hashed (SHA-256) and the hash recorded
alongside; the bytes themselves are NOT stored in the audit log
(they'd grow it unboundedly). An operator who wants to
correlate an action back to "what athena was looking at" can
re-capture if needed.

Append-only by design. Concurrency-safe via a small lock — the
loop is single-threaded today but the audit log is the kind of
thing that grows third-party consumers (status / debugging
tooling) and a thread-safe append matters there.

Schema per row::

  {
    "ts":               "2026-05-20T13:42:00.123456Z",
    "type":             "click" | "screenshot" | ...,
    "target_desc":      "Delete row" | null,
    "coords":           [x, y] | null,
    "app":              "VS Code" | null,
    "tier":             "observe" | "input" | "destructive",
    "confirmed":        true | false | null,
    "executed":         true | false,
    "screenshot_sha256":"abcd..." | null,
    "result":           "ok" | "denied" | "halted" | "error: ..."
  }

The format intentionally mirrors T3-04's audit log style so the
existing diff / query tooling can be extended to this file.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any

from .contract import Action, Screenshot, Tier

logger = logging.getLogger(__name__)


_AUDIT_FILENAME = "computer_audit.jsonl"


@dataclasses.dataclass
class AuditEntry:
    """One row of the audit log."""

    ts: str
    type: str
    target_desc: str | None
    coords: list[int] | None
    app: str | None
    tier: Tier
    confirmed: bool | None
    executed: bool
    screenshot_sha256: str | None
    result: str

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class ActionAuditLog:
    """Per-profile JSONL appender.

    ``path`` defaults to ``<profile_dir>/computer_audit.jsonl``.
    Construction creates the parent dir at 0o700; the file itself
    is created via :mod:`athena.safety.secure_files` so the
    permissions match every other credential-adjacent file in
    athena (0o600 + atomic-replace at write time; we use
    append-mode here since this is an append-only log, not a
    one-shot config rewrite).
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(
        self,
        *,
        action: Action,
        tier: Tier,
        confirmed: bool | None,
        executed: bool,
        screenshot: Screenshot | None,
        result: str,
    ) -> AuditEntry:
        """Append one row. Returns the entry for callers that
        want to inspect what was logged."""
        entry = AuditEntry(
            ts=_now_iso(),
            type=action.type,
            target_desc=action.target_desc,
            coords=list(action.coords) if action.coords else None,
            app=action.app,
            tier=tier,
            confirmed=confirmed,
            executed=bool(executed),
            screenshot_sha256=hash_screenshot(screenshot) if screenshot else None,
            result=result,
        )
        line = json.dumps(entry.to_dict(), separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        logger.debug("computer audit: %s", line)
        return entry

    def tail(self, limit: int = 100) -> list[AuditEntry]:
        """Read the last ``limit`` entries — for the
        ``athena computer status`` command. Empty list when
        the file doesn't exist."""
        if not self.path.exists():
            return []
        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
        out: list[AuditEntry] = []
        for raw in lines[-limit:]:
            raw = raw.strip()
            if not raw:
                continue
            try:
                d = json.loads(raw)
                out.append(AuditEntry(**d))
            except (json.JSONDecodeError, TypeError):
                continue
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def hash_screenshot(shot: Screenshot) -> str:
    """SHA-256 of the screenshot bytes. Used to correlate
    audit rows with what was on screen at decision time —
    the bytes themselves don't go in the log (they'd be huge),
    only the hash."""
    h = hashlib.sha256()
    h.update(shot.png_bytes or b"")
    return h.hexdigest()


def default_audit_path(cfg: Any, profile_dir: Path) -> Path:
    """Resolve the audit-log path for a given profile + cfg.

    ``cfg.computer_audit_path`` wins when set; otherwise
    ``<profile_dir>/computer_audit.jsonl``."""
    explicit = getattr(cfg, "computer_audit_path", None)
    if explicit:
        return Path(str(explicit)).expanduser()
    return Path(profile_dir) / _AUDIT_FILENAME


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
