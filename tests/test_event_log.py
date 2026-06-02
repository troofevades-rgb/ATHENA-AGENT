"""Structured per-session event log (audit P1).

Coverage:

  * ``EventLog.log`` writes one JSON line per event with the
    documented schema (ts / session_id / level / kind / data).
  * Secret scrubber redacts sk-... / Bearer / KEY=value patterns
    in event data before the write.
  * File handle opens lazily (a session that never logs leaves
    no empty file behind).
  * ``close()`` flushes + closes; subsequent ``log()`` calls
    silently no-op.
  * Per-session ``get_event_log`` returns the SAME instance for
    the same id (so per-call file-open overhead is amortized).
  * ``close_event_log`` releases the slot (long-lived daemons
    don't accumulate stale writers).
  * Rotation drops oldest files when ``MAX_LOG_FILES`` exceeded.
  * Malformed JSON lines in a partial-write tail are silently
    skipped by ``iter_events``.
  * ``count_errors_within_days`` filters by mtime + level.
  * Thread-safety: two threads logging concurrently produce two
    complete lines, not interleaving halves.
  * Doctor integration: zero errors -> OK; non-zero -> WARN.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from athena import event_log
from athena.event_log import (
    MAX_LOG_FILES,
    EventLog,
    close_event_log,
    count_errors_within_days,
    get_event_log,
    iter_events,
    recent_log_files,
    reset_event_log_registry,
    rotate_logs,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """The ``_LOGS`` dict + cached file handles are process-global.
    Reset around every test so two tests can't share state."""
    reset_event_log_registry()
    yield
    reset_event_log_registry()


# ---------------------------------------------------------------------------
# Single-event write shape
# ---------------------------------------------------------------------------


def test_log_writes_one_line_per_event(tmp_path: Path) -> None:
    target = tmp_path / "session-x.jsonl"
    el = EventLog("x", path=target)
    el.log("provider_error", "error", {"provider": "openai"})
    el.log("tool_error", "error", {"tool": "Bash"})
    el.close()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        rec = json.loads(line)
        assert {"ts", "session_id", "level", "kind", "data"}.issubset(rec.keys())
        assert rec["session_id"] == "x"


def test_log_records_kind_level_data(tmp_path: Path) -> None:
    target = tmp_path / "session-x.jsonl"
    el = EventLog("x", path=target)
    el.log(
        "circuit_breaker",
        "error",
        {"reason": "circuit_breaker:provider_errors", "turn": 7},
    )
    el.close()
    rec = json.loads(target.read_text(encoding="utf-8").strip())
    assert rec["kind"] == "circuit_breaker"
    assert rec["level"] == "error"
    assert rec["data"]["reason"] == "circuit_breaker:provider_errors"
    assert rec["data"]["turn"] == 7


def test_log_ts_is_iso8601_utc(tmp_path: Path) -> None:
    """``ts`` is an ISO-8601 timestamp with the ``+00:00`` UTC
    suffix so external tooling can parse it without ambiguity."""
    from datetime import datetime

    target = tmp_path / "session-x.jsonl"
    el = EventLog("x", path=target)
    el.log("provider_error", "error", {})
    el.close()
    rec = json.loads(target.read_text(encoding="utf-8").strip())
    parsed = datetime.fromisoformat(rec["ts"])
    assert parsed.tzinfo is not None  # UTC-aware


# ---------------------------------------------------------------------------
# Lazy open / no-empty-file invariant
# ---------------------------------------------------------------------------


def test_no_file_created_until_first_log(tmp_path: Path) -> None:
    target = tmp_path / "session-empty.jsonl"
    el = EventLog("empty", path=target)
    el.close()
    # No log() call -> no file on disk.
    assert not target.exists()


def test_file_appears_after_first_log(tmp_path: Path) -> None:
    target = tmp_path / "session-first.jsonl"
    el = EventLog("first", path=target)
    el.log("provider_error", "error", {})
    assert target.exists()
    el.close()


# ---------------------------------------------------------------------------
# Closed-writer behaviour
# ---------------------------------------------------------------------------


def test_log_after_close_is_silent_noop(tmp_path: Path) -> None:
    """Writes after close MUST silently no-op rather than raising
    (a shutdown race could fire one last event and we shouldn't
    crash the close path on it)."""
    target = tmp_path / "session-x.jsonl"
    el = EventLog("x", path=target)
    el.log("provider_error", "error", {"first": True})
    el.close()
    # No raise:
    el.log("provider_error", "error", {"after": "close"})
    # Second event did NOT land on disk.
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


# ---------------------------------------------------------------------------
# Per-session registry
# ---------------------------------------------------------------------------


def test_get_event_log_returns_same_instance_for_same_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Repeat lookups return the SAME EventLog object so per-call
    file-open overhead is amortized across many events in one
    session."""
    monkeypatch.setattr(event_log, "_log_dir", lambda: tmp_path)
    a = get_event_log("session-abc")
    b = get_event_log("session-abc")
    assert a is b


def test_close_event_log_releases_slot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """After close, the next ``get_event_log`` returns a fresh
    instance (not the closed one). Otherwise long-lived daemons
    would accumulate closed writers in the dict."""
    monkeypatch.setattr(event_log, "_log_dir", lambda: tmp_path)
    a = get_event_log("session-abc")
    close_event_log("session-abc")
    b = get_event_log("session-abc")
    assert a is not b


# ---------------------------------------------------------------------------
# Secret scrubbing
# ---------------------------------------------------------------------------


def test_scrubs_secrets_inside_event_data(tmp_path: Path) -> None:
    """The crash_log scrubber runs over every string value before
    serialization. ``sk-...`` API keys must not survive to disk
    even when an exception message includes one."""
    target = tmp_path / "session-x.jsonl"
    el = EventLog("x", path=target)
    el.log(
        "provider_error",
        "error",
        {
            "provider": "openrouter",
            "message": "401 from sk-or-v1-abcdef1234567890 -- check key",
        },
    )
    el.close()
    text = target.read_text(encoding="utf-8")
    assert "sk-or-v1-abcdef1234567890" not in text
    assert "<redacted-secret>" in text


def test_scrubs_inside_nested_data(tmp_path: Path) -> None:
    """The scrubber recurses through nested dicts / lists so a
    secret buried inside a structured field still gets caught."""
    target = tmp_path / "session-x.jsonl"
    el = EventLog("x", path=target)
    el.log(
        "tool_error",
        "error",
        {
            "tool": "Bash",
            "env": {
                "PATH": "/usr/local/bin",
                "ANTHROPIC_API_KEY": "sk-ant-secret123abc",
            },
            "stderr_tail": ["normal output", "Bearer eyJtoken-abc-123"],
        },
    )
    el.close()
    text = target.read_text(encoding="utf-8")
    assert "sk-ant-secret123abc" not in text
    assert "eyJtoken-abc-123" not in text


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


def test_rotation_drops_oldest_beyond_keep(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Files older than the cap get unlinked by mtime. Newest
    survive."""
    import os

    for i in range(5):
        f = tmp_path / f"session-202{i}.jsonl"
        f.write_text("{}", encoding="utf-8")
        ts = time.time() - (5 - i) * 60
        os.utime(f, (ts, ts))

    monkeypatch.setattr(event_log, "_log_dir", lambda: tmp_path)
    rotate_logs(keep=2)

    remaining = sorted(p.name for p in tmp_path.glob("session-*.jsonl"))
    assert len(remaining) == 2
    # The two newest (highest indices) survive.
    assert remaining == ["session-2023.jsonl", "session-2024.jsonl"]


def test_rotation_no_op_below_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f"session-{i}.jsonl").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(event_log, "_log_dir", lambda: tmp_path)
    rotate_logs(keep=10)
    assert len(list(tmp_path.glob("session-*.jsonl"))) == 3


def test_default_cap_bounded() -> None:
    """``MAX_LOG_FILES`` stays in a sane range so unbounded growth
    can't happen on a long-lived gateway."""
    assert 10 <= MAX_LOG_FILES <= 10000


# ---------------------------------------------------------------------------
# iter_events + count_errors
# ---------------------------------------------------------------------------


def test_iter_events_yields_each_event(tmp_path: Path) -> None:
    target = tmp_path / "session-x.jsonl"
    el = EventLog("x", path=target)
    el.log("provider_error", "error", {"a": 1})
    el.log("tool_error", "warn", {"b": 2})
    el.close()
    events = list(iter_events([target]))
    assert len(events) == 2
    assert events[0]["data"]["a"] == 1
    assert events[1]["data"]["b"] == 2


def test_iter_events_skips_malformed_lines(tmp_path: Path) -> None:
    """A partial-write tail (a half-written final line from a hard
    crash) is silently skipped rather than raising. Pins the
    operator UX: ``cat`` a session file even after a crash and the
    reader doesn't choke on the tail."""
    target = tmp_path / "session-corrupt.jsonl"
    target.write_text(
        '{"ts": "x", "session_id": "s", "level": "error", "kind": "k", "data": {}}\n'
        "{not a complete json line\n"
        '{"ts": "y", "session_id": "s", "level": "error", "kind": "k", "data": {}}\n',
        encoding="utf-8",
    )
    events = list(iter_events([target]))
    assert len(events) == 2


def test_count_errors_within_days_filters_by_mtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Old session files don't count; recent ones do."""
    import os

    # Recent session: 1 error event.
    recent = tmp_path / "session-recent.jsonl"
    recent.write_text(
        '{"ts": "x", "session_id": "r", "level": "error", "kind": "tool_error", "data": {}}\n',
        encoding="utf-8",
    )
    os.utime(recent, (time.time() - 3600, time.time() - 3600))

    # Old session: 5 errors, 10 days ago.
    old = tmp_path / "session-old.jsonl"
    old.write_text(
        '{"ts": "x", "session_id": "o", "level": "error", "kind": "tool_error", "data": {}}\n' * 5,
        encoding="utf-8",
    )
    old_ts = time.time() - 10 * 86400
    os.utime(old, (old_ts, old_ts))

    monkeypatch.setattr(event_log, "_log_dir", lambda: tmp_path)

    assert count_errors_within_days(1) == 1
    assert count_errors_within_days(30) == 6  # 1 recent + 5 old


def test_count_errors_ignores_non_error_level(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only ``level == "error"`` counts. Warns are visible but
    don't trip the "recent failures" surface."""
    import os

    target = tmp_path / "session-x.jsonl"
    target.write_text(
        '{"ts": "x", "session_id": "x", "level": "warn", "kind": "k", "data": {}}\n'
        '{"ts": "y", "session_id": "x", "level": "error", "kind": "k", "data": {}}\n'
        '{"ts": "z", "session_id": "x", "level": "warn", "kind": "k", "data": {}}\n',
        encoding="utf-8",
    )
    os.utime(target, (time.time() - 3600, time.time() - 3600))
    monkeypatch.setattr(event_log, "_log_dir", lambda: tmp_path)

    assert count_errors_within_days(1) == 1


def test_recent_log_files_sorts_newest_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``ls -lt`` semantics so doctor can show "most recent session
    -> /path/to/log"."""
    import os

    for i in range(3):
        f = tmp_path / f"session-{i}.jsonl"
        f.write_text("{}", encoding="utf-8")
        os.utime(f, (time.time() - (3 - i) * 60, time.time() - (3 - i) * 60))
    monkeypatch.setattr(event_log, "_log_dir", lambda: tmp_path)
    listing = recent_log_files()
    # Index 2 has the most recent mtime.
    assert listing[0].name == "session-2.jsonl"
    assert listing[-1].name == "session-0.jsonl"


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_concurrent_writes_produce_complete_lines(tmp_path: Path) -> None:
    """Two threads hammering the same writer must produce N complete
    JSON lines, not N-with-interleaving-halves. The writer lock
    serializes appends so the format is preserved under contention."""
    target = tmp_path / "session-concurrent.jsonl"
    el = EventLog("c", path=target)

    def _hammer(i: int) -> None:
        for j in range(50):
            el.log(
                "provider_error",
                "error",
                {"thread": i, "n": j, "filler": "x" * 200},
            )

    threads = [threading.Thread(target=_hammer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    el.close()

    # All 200 (4 threads * 50 events) lines are well-formed JSON.
    events = list(iter_events([target]))
    assert len(events) == 4 * 50
    # Each event's data parsed correctly -- if there was line
    # interleaving, json.loads would have raised.


# ---------------------------------------------------------------------------
# Doctor integration
# ---------------------------------------------------------------------------


def test_doctor_event_log_check_ok_when_no_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from athena.cli import doctor

    monkeypatch.setattr(
        "athena.event_log.count_errors_within_days",
        lambda days: 0,
    )
    monkeypatch.setattr(
        "athena.event_log.recent_log_files",
        lambda within_days=None: [],
    )
    result = doctor._check_recent_event_log_errors()
    assert result.severity == "ok"
    assert "0 error" in result.detail


def test_doctor_event_log_check_warn_when_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from athena.cli import doctor

    monkeypatch.setattr(
        "athena.event_log.count_errors_within_days",
        lambda days: 12,
    )
    monkeypatch.setattr(
        "athena.event_log.recent_log_files",
        lambda within_days=None: [tmp_path / "session-x.jsonl"],
    )
    result = doctor._check_recent_event_log_errors()
    assert result.severity == "warn"
    assert "12 error" in result.detail
    assert result.extra["error_count"] == 12
