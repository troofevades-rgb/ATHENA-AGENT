"""Capture log + politeness throttle for browser navigation (T4-03.3).

Two responsibilities:

  1. **Capture log**: every navigation appends a JSONL row to
     ``cfg.browser_capture_path`` (default
     ``<profile_dir>/browser_capture.jsonl``). Carries
     ``ts / session_id / url / final_url / status / title /
     screenshot_path / content_sha256``. This is the
     accountability trail — what was visited, when, and what it
     looked like. The page bytes themselves are NOT stored;
     only a SHA-256 (provenance over volume, same calculus as
     T4-01.2 / T6-04.4).

  2. **Politeness throttle**: a per-domain minimum interval
     between navigations (default 1s). The persistent-browser
     persistence model lets the agent navigate fast — without
     a throttle, "search → click result → click another result"
     hammers a single site. The throttle is a courtesy default
     that the operator can dial down for trusted internal
     targets.

The raw append-only JSONL pattern matches T6-04's
``computer/audit.py`` and T4-01.2's vision hash-log. Same
justification — operational metadata, append-only, not agent-
driven content mutation — so this module ends up on the
:mod:`tests.safety.test_no_raw_writes` allowlist.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import threading
import time
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:  # pragma: no cover
        return ""


class CaptureLogger:
    """Append-only capture log + per-domain politeness throttle.

    Construction is cheap — no I/O until the first :meth:`log`
    or :meth:`throttle` call. The throttle's "last nav per
    domain" map lives in memory only; restarts don't carry it
    over (intentional — a fresh session shouldn't pay last
    session's wait penalty).
    """

    def __init__(
        self,
        path: Path | str,
        *,
        min_interval_s: float = 1.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.path = Path(path)
        self.min_interval_s = float(min_interval_s)
        self._last_nav_by_domain: dict[str, float] = {}
        self._lock = threading.Lock()
        # Injectable so tests can assert "sleep was called" without
        # actually waiting.
        self._sleep = sleep_fn

    # ----- politeness -----

    def throttle(self, url: str) -> float:
        """Sleep if this domain was navigated less than
        ``min_interval_s`` seconds ago. Returns the elapsed
        sleep duration (for telemetry / tests).

        Cross-domain navigations don't trigger a sleep — each
        domain has its own "last seen" timestamp."""
        if self.min_interval_s <= 0:
            return 0.0
        dom = _domain(url)
        if not dom:
            return 0.0
        now = time.monotonic()
        last = self._last_nav_by_domain.get(dom)
        slept = 0.0
        if last is not None:
            elapsed = now - last
            if elapsed < self.min_interval_s:
                wait = self.min_interval_s - elapsed
                self._sleep(wait)
                slept = wait
        # Stamp the wakeup time, not the entry time, so a long
        # sleep here doesn't immediately re-throttle on the
        # next call.
        self._last_nav_by_domain[dom] = time.monotonic()
        return slept

    # ----- capture log -----

    def log(
        self,
        *,
        session_id: str,
        url: str,
        final_url: str,
        status: int | None,
        title: str,
        screenshot_path: str = "",
        content: str = "",
    ) -> dict[str, Any]:
        """Append one capture row. Returns the entry for
        callers that want to inspect what was logged."""
        entry = {
            "ts": _now_iso(),
            "session_id": session_id,
            "url": url,
            "final_url": final_url,
            "status": int(status) if status is not None else 0,
            "title": title,
            "screenshot_path": screenshot_path,
            "content_sha256": (
                hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
                if content
                else ""
            ),
        }
        line = json.dumps(entry, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        logger.debug("browser capture: %s", line)
        return entry

    def tail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Read the last ``limit`` entries. [] when the file
        doesn't exist yet."""
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        out: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("malformed browser capture line: %r", line[:120])
        return out
