"""Structured per-session event log at ``~/.athena/logs/``.

Different from Python's stdlib ``logging`` (which the codebase uses
for developer-level debug output to stderr / a rotating file): this
module captures a structured incident-review timeline. One JSONL
file per session, one event per line, schema-stable so external
tooling (a Slack-bot triage script, ``jq`` queries, an
observability backend) can rely on it.

Pairs with :mod:`athena.crash_log`. When something CRASHES, the
crash log captures the exception + live state. When something
FAILS WITHOUT CRASHING (provider 400, tool error, circuit breaker
trip), the event log captures it in the timeline. Together they
give a full picture of what happened in a problem session.

What's captured (v1):

  * ``provider_error`` -- emitted when ``_stream_one``'s except
    block fires (transport failure, 400 from a deprecated model,
    auth rejection, etc.). Counts the dogfood pattern that
    motivated the circuit breaker.
  * ``tool_error`` -- emitted when ``tools.dispatch`` raises during
    a tool call. The tool's name + the exception type / message
    land in ``data``.
  * ``circuit_breaker`` -- emitted when ``_fire_stop`` fires with
    a ``circuit_breaker:<reason>`` stop. Helps operators see WHY
    the turn ended without ever hitting max_turn_steps.
  * ``plugin_error`` -- emitted when the plugin dispatcher's
    catch-all catches an exception from a plugin hook. Currently
    these are swallowed with a logger.debug; surfacing them in the
    event log keeps the swallow semantics (plugins can't break
    the agent) while making the failure visible.

What's NOT captured (v1):

  * Successful tool calls (already counted in
    ``Stats.tool_call_counts``; logging each one is just noise).
  * Successful turns.
  * Debug-level developer output (use Python's logging for that).
  * MCP server stderr (already routed via the gateway's
    on_message callback).

Schema (one JSON object per line):

    {
      "ts": "2026-05-31T22:00:00Z",     # ISO-8601 UTC
      "session_id": "uuid",
      "level": "warn" | "error",
      "kind": "provider_error" | "tool_error" | "circuit_breaker"
              | "plugin_error" | "mcp_error",
      "data": { ... }                    # event-specific, scrubbed
    }

Performance:

  * One file handle per active session, opened lazily on first
    write, kept open for the session's lifetime.
  * Each event is JSON-serialized, written, and flushed
    immediately so a crash captures the most recent event.
  * Bounded rotation at ``MAX_LOG_FILES`` (default 200 sessions).
    Oldest dropped by file mtime when the cap is exceeded.

Privacy:

  * Reuses :func:`athena.crash_log._scrub` over every string before
    serialization. ``sk-...`` API keys, Bearer tokens, and
    ``*_API_KEY=...`` patterns are replaced with
    ``<redacted-secret>``.
  * No conversation content lands here -- the event ``data`` is
    structured metadata (tool name, exception type / message,
    provider name) only.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .crash_log import _scrub

logger = logging.getLogger(__name__)

# Bounded rotation. Each file is small (a few KB typical, low-double-
# digit KB for very chatty sessions). 200 * tens-of-KB = a few MB
# upper bound on disk.
MAX_LOG_FILES = 200

# Documented event kinds. Adding a new kind: add the literal here,
# pin a test, and surface it in doctor if it should affect the
# health summary.
EventKind = Literal[
    "provider_error",
    "tool_error",
    "circuit_breaker",
    "plugin_error",
    "mcp_error",
]
EventLevel = Literal["warn", "error"]


def _log_dir() -> Path:
    """Resolve ``~/.athena/logs/``. Auto-creates the directory.
    Indirected so tests can monkeypatch."""
    p = Path.home() / ".athena" / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _log_path(session_id: str) -> Path:
    """Compute the JSONL path for ``session_id``. Filename uses the
    session_id verbatim so two `ls` listings on different machines
    sort identically and operators can copy-paste a session id and
    find its log."""
    return _log_dir() / f"session-{session_id}.jsonl"


def _scrub_value(value: Any) -> Any:
    """Recursively scrub strings inside a JSON-serializable value.
    Lists / dicts are walked; scalars pass through (or scrub if
    string)."""
    if isinstance(value, str):
        return _scrub(value)
    if isinstance(value, Mapping):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(v) for v in value]
    return value


class EventLog:
    """Per-session event log writer. Thread-safe (the writer lock
    serializes appends so two threads firing tool errors
    concurrently produce two complete lines rather than interleaving
    halves)."""

    def __init__(self, session_id: str, path: Path | None = None) -> None:
        self.session_id = session_id
        self._path = path or _log_path(session_id)
        # Lazy open -- the file is created on first write so a
        # session that never logs anything doesn't leave an empty
        # file behind.
        self._fh: Any = None
        self._lock = threading.Lock()
        self._closed = False

    # ---- write API ----

    def log(
        self,
        kind: EventKind,
        level: EventLevel = "error",
        data: Mapping[str, Any] | None = None,
    ) -> None:
        """Write one event to the log. Idempotent on close (writes
        after close are silently dropped -- the operator already
        ended the session).

        Never raises. A write failure logs at DEBUG and returns; the
        event log is observability, not correctness, and must never
        break the agent."""
        if self._closed:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "level": level,
            "kind": kind,
            "data": _scrub_value(dict(data or {})),
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        try:
            with self._lock:
                if self._fh is None:
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                    self._fh = open(self._path, "a", encoding="utf-8")
                self._fh.write(line)
                self._fh.flush()
        except Exception as e:  # noqa: BLE001
            logger.debug("event_log write failed: %s", e)

    def close(self) -> None:
        """Flush + close the underlying file handle. Subsequent
        ``log()`` calls are no-ops."""
        with self._lock:
            self._closed = True
            if self._fh is not None:
                try:
                    self._fh.flush()
                    self._fh.close()
                except Exception:  # noqa: BLE001
                    pass
                self._fh = None

    @property
    def path(self) -> Path:
        return self._path


# ---- per-process session -> log map ----------------------------------

# Module-level state: maps session_id -> EventLog. Keeps the writer
# alive for the session's lifetime and lets the runtime fetch the
# active logger from anywhere via ``get_event_log(session_id)``.
_LOGS: dict[str, EventLog] = {}
_LOGS_LOCK = threading.Lock()


def get_event_log(session_id: str) -> EventLog:
    """Return the EventLog for ``session_id``, creating it on first
    call. Subsequent calls for the same id return the same instance
    so per-call file-open overhead is amortized."""
    with _LOGS_LOCK:
        existing = _LOGS.get(session_id)
        if existing is not None and not existing._closed:
            return existing
        eventlog = EventLog(session_id)
        _LOGS[session_id] = eventlog
        return eventlog


def close_event_log(session_id: str) -> None:
    """Close and drop the EventLog for ``session_id``. Called by
    ``Agent.close()`` so the file handle is released and the slot
    in ``_LOGS`` doesn't leak across sessions in long-lived
    daemons (gateway / cron)."""
    with _LOGS_LOCK:
        existing = _LOGS.pop(session_id, None)
    if existing is not None:
        existing.close()


def reset_event_log_registry() -> None:
    """Drop every cached EventLog. Used by tests so a fresh
    session_id always gets a fresh writer."""
    with _LOGS_LOCK:
        for log in _LOGS.values():
            log.close()
        _LOGS.clear()


# ---- rotation --------------------------------------------------------


def _rotate(log_dir: Path, keep: int) -> None:
    """Drop the oldest log files until at most ``keep`` remain.
    Sort by mtime ascending so the OLDEST get deleted first."""
    if keep <= 0:
        return
    try:
        files = [
            p
            for p in log_dir.iterdir()
            if p.is_file() and p.name.startswith("session-") and p.suffix == ".jsonl"
        ]
    except OSError:
        return
    if len(files) <= keep:
        return
    files.sort(key=lambda p: p.stat().st_mtime)
    for p in files[: len(files) - keep]:
        try:
            p.unlink()
        except OSError:
            logger.debug("event_log rotate: could not delete %s", p)


def rotate_logs(keep: int = MAX_LOG_FILES, log_dir: Path | None = None) -> None:
    """Public entry point. Called by the agent on session start so
    the cap is enforced without operators having to manage it."""
    _rotate(log_dir or _log_dir(), keep)


# ---- reader API ------------------------------------------------------


def recent_log_files(
    log_dir: Path | None = None,
    *,
    within_days: int | None = None,
) -> list[Path]:
    """List session log files, optionally filtered to the last
    ``within_days``. Sorted newest-first by mtime."""
    target = log_dir or _log_dir()
    if not target.exists():
        return []
    files = [
        p
        for p in target.iterdir()
        if p.is_file() and p.name.startswith("session-") and p.suffix == ".jsonl"
    ]
    if within_days is not None:
        cutoff = time.time() - within_days * 86400
        files = [p for p in files if p.stat().st_mtime >= cutoff]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def iter_events(
    paths: Iterable[Path],
) -> Iterable[dict[str, Any]]:
    """Yield every parsed event from ``paths``. Malformed lines are
    silently skipped (a partial JSON line at the tail from a hard
    crash isn't a fatal read error)."""
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        yield json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue


def count_errors_within_days(
    days: int,
    *,
    log_dir: Path | None = None,
) -> int:
    """Count events with ``level == "error"`` across all session
    logs younger than ``days``. Used by ``athena doctor`` to
    surface a recent-failure summary."""
    files = recent_log_files(log_dir=log_dir, within_days=days)
    return sum(1 for ev in iter_events(files) if ev.get("level") == "error")


__all__: tuple[str, ...] = (
    "EventKind",
    "EventLevel",
    "EventLog",
    "MAX_LOG_FILES",
    "close_event_log",
    "count_errors_within_days",
    "get_event_log",
    "iter_events",
    "recent_log_files",
    "reset_event_log_registry",
    "rotate_logs",
)
