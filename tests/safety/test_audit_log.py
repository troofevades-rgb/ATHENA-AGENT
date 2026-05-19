"""Phase 17.4 — append-only JSONL mutation audit log."""

from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path

import pytest

from athena.safety import audit as audit_mod
from athena.safety.audit import (
    MutationAuditLog,
    MutationRecord,
    now_iso,
    sha_of_file,
)


@pytest.fixture
def audit_dir(tmp_path: Path) -> Path:
    return tmp_path / "audit"


@pytest.fixture
def log(audit_dir: Path) -> MutationAuditLog:
    return MutationAuditLog(audit_dir)


def _make_record(i: int) -> MutationRecord:
    return MutationRecord(
        timestamp=now_iso(),
        write_origin="curator",
        session_id=f"s-{i}",
        parent_session_id=None,
        tool_name="skill_manage",
        tool_call_id=f"call-{i}",
        path="/skills/demo/SKILL.md",
        snapshot_id=f"snap-{i}",
        sha_before="a" * 64,
        sha_after="b" * 64,
        byte_delta=i,
    )


# ---- single-thread basic round-trip --------------------------------------


def test_append_creates_audit_directory(tmp_path: Path) -> None:
    """Constructor mkdirs even when the parent doesn't exist."""
    log = MutationAuditLog(tmp_path / "nested" / "audit")
    assert (tmp_path / "nested" / "audit").is_dir()
    log.append(_make_record(0))


def test_record_round_trips_through_jsonl(log: MutationAuditLog) -> None:
    record = _make_record(7)
    log.append(record)
    path = log._current_path()
    line = path.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    # Every field present, values exact.
    assert parsed["timestamp"] == record.timestamp
    assert parsed["session_id"] == "s-7"
    assert parsed["tool_call_id"] == "call-7"
    assert parsed["byte_delta"] == 7
    assert parsed["snapshot_id"] == "snap-7"
    assert parsed["sha_before"] == "a" * 64
    assert parsed["sha_after"] == "b" * 64


def test_jsonl_is_compact_one_line_per_record(log: MutationAuditLog) -> None:
    """Compact separators — no whitespace padding the JSON. This
    matters for log size and for grep/jq pipelines."""
    log.append(_make_record(1))
    line = log._current_path().read_text(encoding="utf-8").strip()
    # Compact form has no ", " or ": " sequences inside the object.
    assert ", " not in line
    assert ": " not in line


# ---- concurrency ---------------------------------------------------------


def test_concurrent_appends_preserve_every_line(log: MutationAuditLog) -> None:
    """100 threads each writing one record — all 100 lines must be
    present, intact, parseable. No interleaving, no dropped writes."""
    n_threads = 100

    def worker(i: int) -> None:
        log.append(_make_record(i))

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    path = log._current_path()
    raw = path.read_text(encoding="utf-8")
    lines = [line for line in raw.splitlines() if line]
    assert len(lines) == n_threads
    # Every line parses.
    parsed = [json.loads(line) for line in lines]
    seen_ids = {p["session_id"] for p in parsed}
    assert seen_ids == {f"s-{i}" for i in range(n_threads)}


# ---- month rollover ------------------------------------------------------


def test_month_rollover_changes_filename(
    log: MutationAuditLog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the calendar month changes between two appends, the second
    append lands in a new file (and the first file is left intact)."""
    real_datetime = audit_mod.dt.datetime

    class _Frozen:
        moment: dt.datetime = dt.datetime(2026, 5, 17, tzinfo=dt.timezone.utc)

        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            return cls.moment

    class _DTShim:
        datetime = _Frozen
        timezone = dt.timezone
        timedelta = dt.timedelta

    monkeypatch.setattr(audit_mod, "dt", _DTShim)

    log.append(_make_record(1))
    may_path = log._current_path()
    assert may_path.name == "mutations-2026-05.jsonl"

    # Move to June.
    _Frozen.moment = dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc)
    log.append(_make_record(2))
    june_path = log._current_path()
    assert june_path.name == "mutations-2026-06.jsonl"

    # Both files exist independently.
    assert may_path.exists()
    assert june_path.exists()
    assert may_path.read_text(encoding="utf-8").count("\n") == 1
    assert june_path.read_text(encoding="utf-8").count("\n") == 1


# ---- append mode preservation -------------------------------------------


def test_existing_file_is_appended_not_truncated(log: MutationAuditLog) -> None:
    """Verify open mode is "a" — repeated appends grow the file."""
    log.append(_make_record(1))
    log.append(_make_record(2))
    log.append(_make_record(3))
    path = log._current_path()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    ids = [json.loads(line)["session_id"] for line in lines]
    assert ids == ["s-1", "s-2", "s-3"]


def test_pre_existing_content_survives_append(
    audit_dir: Path,
    log: MutationAuditLog,
) -> None:
    """If the file already exists with content from a prior session,
    new appends extend it rather than wiping it."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    pre_existing = log._current_path()
    pre_existing.write_text(
        '{"timestamp":"old","write_origin":"curator",'
        '"session_id":"prior","parent_session_id":null,'
        '"tool_name":"x","tool_call_id":"y","path":"/p",'
        '"snapshot_id":null,"sha_before":null,"sha_after":null,'
        '"byte_delta":0}\n',
        encoding="utf-8",
    )
    log.append(_make_record(42))
    lines = pre_existing.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["session_id"] == "prior"
    assert json.loads(lines[1])["session_id"] == "s-42"


# ---- sha_of_file --------------------------------------------------------


def test_sha_of_file_matches_known_hash(tmp_path: Path) -> None:
    """sha of empty file == sha256("") == e3b0c44...."""
    p = tmp_path / "empty"
    p.write_bytes(b"")
    assert sha_of_file(p) == ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")


def test_sha_of_file_content_changes_change_hash(tmp_path: Path) -> None:
    p = tmp_path / "file.txt"
    p.write_text("alpha", encoding="utf-8")
    s1 = sha_of_file(p)
    p.write_text("beta", encoding="utf-8")
    s2 = sha_of_file(p)
    assert s1 != s2
    assert s1 is not None and len(s1) == 64
    assert s2 is not None and len(s2) == 64


def test_sha_of_file_returns_none_for_missing(tmp_path: Path) -> None:
    assert sha_of_file(tmp_path / "missing") is None


def test_sha_of_file_returns_none_for_directory(tmp_path: Path) -> None:
    d = tmp_path / "dir"
    d.mkdir()
    assert sha_of_file(d) is None


# ---- now_iso --------------------------------------------------------------


def test_now_iso_is_parseable_utc() -> None:
    parsed = dt.datetime.fromisoformat(now_iso())
    assert parsed.tzinfo is not None
