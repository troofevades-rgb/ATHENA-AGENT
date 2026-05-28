"""Optional polling watcher for skill directories.

When ``cfg.skills_autoload`` is True, the Agent starts one of these
on a daemon thread at construction time. The watcher snapshots
``<base>/<name>/SKILL.md`` mtimes for every discoverable skill across
both search paths (``~/.athena/skills/`` and
``<workspace>/.athena/skills/``) every ``poll_interval`` seconds.

When the snapshot diverges (file added, modified, or removed), the
watcher invalidates the body cache for affected names and calls a
caller-supplied ``on_change`` callback. The typical callback is
:meth:`Agent.reload_skills` -- delivered via a closure so the watcher
module doesn't need to know about Agent internals.

A polling watcher rather than ``watchdog`` so this stays dep-free.
Polling is plenty here: skill files are tiny, edits are rare, and the
default 2s interval is well below human reaction time. Walking the
two trees and stat-ing each SKILL.md is a few dozen syscalls per
poll, which is negligible.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .discovery import search_paths

logger = logging.getLogger(__name__)

ChangeCallback = Callable[[], None]


def _snapshot(workspace: Path | None) -> dict[Path, float]:
    """Walk each skill base and return ``{SKILL.md path -> mtime}``.

    Missing trees produce an empty contribution rather than raising
    so the snapshot can run before either base exists.
    """
    out: dict[Path, float] = {}
    for base in search_paths(workspace):
        try:
            entries = list(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            skill_md = entry / "SKILL.md"
            try:
                stat = skill_md.stat()
            except OSError:
                continue
            out[skill_md] = stat.st_mtime
    return out


class SkillWatcher:
    """Polling watcher; one per Agent. Daemon thread, fire-and-forget.

    Construction does NOT start the thread -- call :meth:`start`. The
    thread loops until :meth:`stop` is called or the process exits.
    """

    def __init__(
        self,
        workspace: Path | None,
        on_change: ChangeCallback,
        *,
        poll_interval: float = 2.0,
    ) -> None:
        self.workspace = workspace
        self.on_change = on_change
        self.poll_interval = max(0.5, float(poll_interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: dict[Path, float] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._last = _snapshot(self.workspace)
        self._thread = threading.Thread(
            target=self._run, name="athena-skill-watcher", daemon=True,
        )
        self._thread.start()
        logger.info(
            "skill watcher started: %d skill(s) tracked, poll=%.1fs",
            len(self._last), self.poll_interval,
        )

    def stop(self, *, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.wait(self.poll_interval):
            try:
                current = _snapshot(self.workspace)
            except Exception:  # noqa: BLE001
                logger.debug("skill watcher snapshot failed", exc_info=True)
                continue
            if current == self._last:
                continue
            added = set(current) - set(self._last)
            removed = set(self._last) - set(current)
            modified = {
                p for p in current
                if p in self._last and current[p] != self._last[p]
            }
            self._last = current
            self._on_changes(added=added, removed=removed, modified=modified)

    def _on_changes(
        self,
        *,
        added: set[Path],
        removed: set[Path],
        modified: set[Path],
    ) -> None:
        logger.info(
            "skill watcher: +%d -%d ~%d", len(added), len(removed), len(modified),
        )
        try:
            from . import loader as _loader
            _loader._BODY_CACHE.clear()
        except Exception:  # noqa: BLE001
            logger.debug("skill watcher: body cache clear failed", exc_info=True)
        try:
            self.on_change()
        except Exception:  # noqa: BLE001
            logger.exception("skill watcher on_change callback raised")
