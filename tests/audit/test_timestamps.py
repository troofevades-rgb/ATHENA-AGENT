"""Tests for athena.audit.timestamps (T3-04)."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from athena.audit.timestamps import TimestampParseError, parse_timestamp

_FIXED_NOW = _dt.datetime(2026, 5, 20, 12, 0, 0)


# ---------------------------------------------------------------------------
# ISO 8601
# ---------------------------------------------------------------------------


def test_parse_iso_with_z() -> None:
    assert parse_timestamp("2026-05-15T00:00:00Z") == _dt.datetime(2026, 5, 15, 0, 0, 0)


def test_parse_iso_with_explicit_offset() -> None:
    # +00:00 → UTC-naive
    assert parse_timestamp("2026-05-15T00:00:00+00:00") == _dt.datetime(2026, 5, 15, 0, 0, 0)
    # +02:00 → normalised to 22:00 the previous day UTC
    assert parse_timestamp("2026-05-15T02:00:00+02:00") == _dt.datetime(2026, 5, 15, 0, 0, 0)


def test_parse_iso_date_only() -> None:
    assert parse_timestamp("2026-05-15") == _dt.datetime(2026, 5, 15, 0, 0, 0)


def test_parse_invalid_raises() -> None:
    with pytest.raises(TimestampParseError):
        parse_timestamp("not-a-timestamp")
    with pytest.raises(TimestampParseError):
        parse_timestamp("")


# ---------------------------------------------------------------------------
# Relative
# ---------------------------------------------------------------------------


def test_parse_relative_seconds() -> None:
    assert parse_timestamp("30s", now=_FIXED_NOW) == _FIXED_NOW - _dt.timedelta(seconds=30)


def test_parse_relative_minutes() -> None:
    assert parse_timestamp("5m", now=_FIXED_NOW) == _FIXED_NOW - _dt.timedelta(minutes=5)


def test_parse_relative_24h() -> None:
    assert parse_timestamp("24h", now=_FIXED_NOW) == _FIXED_NOW - _dt.timedelta(hours=24)


def test_parse_relative_3d() -> None:
    assert parse_timestamp("3d", now=_FIXED_NOW) == _FIXED_NOW - _dt.timedelta(days=3)


def test_parse_relative_1w() -> None:
    assert parse_timestamp("1w", now=_FIXED_NOW) == _FIXED_NOW - _dt.timedelta(weeks=1)


def test_parse_relative_unknown_unit_falls_through_to_iso() -> None:
    # "5y" doesn't match the relative regex; parser tries ISO and
    # fails — TimestampParseError, not a silent accept.
    with pytest.raises(TimestampParseError):
        parse_timestamp("5y", now=_FIXED_NOW)


# ---------------------------------------------------------------------------
# Special tokens
# ---------------------------------------------------------------------------


def test_parse_now_uses_injected_clock() -> None:
    assert parse_timestamp("now", now=_FIXED_NOW) == _FIXED_NOW


def test_parse_now_returns_recent_utc() -> None:
    """Without ``now=``, the parser uses the real UTC clock."""
    before = _dt.datetime.utcnow()
    parsed = parse_timestamp("now")
    after = _dt.datetime.utcnow()
    # Allow a tiny skew for fast machines.
    assert before <= parsed <= after + _dt.timedelta(seconds=1)


def test_parse_boot_requires_session_log_path() -> None:
    with pytest.raises(TimestampParseError, match="no active session log"):
        parse_timestamp("boot")


def test_parse_boot_reads_first_message_timestamp(tmp_path: Path) -> None:
    log = tmp_path / "session.jsonl"
    log.write_text(
        json.dumps(
            {
                "role": "system",
                "content": "init",
                "ts": "2026-05-19T08:30:00Z",
            }
        )
        + "\n"
        + json.dumps({"role": "user", "content": "later"})
        + "\n",
        encoding="utf-8",
    )
    assert parse_timestamp("boot", session_log_path=log) == _dt.datetime(2026, 5, 19, 8, 30, 0)


def test_parse_session_start_aliases_boot(tmp_path: Path) -> None:
    log = tmp_path / "s.jsonl"
    log.write_text(
        json.dumps({"role": "system", "ts": "2026-05-19T08:30:00Z"}) + "\n",
        encoding="utf-8",
    )
    assert parse_timestamp("session-start", session_log_path=log) == _dt.datetime(
        2026, 5, 19, 8, 30, 0
    )


def test_parse_boot_with_no_timestamp_in_log_raises(tmp_path: Path) -> None:
    log = tmp_path / "s.jsonl"
    log.write_text(
        json.dumps({"role": "system", "content": "no ts here"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(TimestampParseError, match="no parseable timestamp"):
        parse_timestamp("boot", session_log_path=log)


# ---------------------------------------------------------------------------
# last-checkpoint
# ---------------------------------------------------------------------------


def test_parse_last_checkpoint_requires_profile_dir() -> None:
    with pytest.raises(TimestampParseError, match="no profile directory"):
        parse_timestamp("last-checkpoint")


def test_parse_last_checkpoint_no_checkpoints_raises(tmp_path: Path) -> None:
    pdir = tmp_path / "profile"
    pdir.mkdir()
    with pytest.raises(TimestampParseError, match="no checkpoints under"):
        parse_timestamp("last-checkpoint", profile_dir=pdir)


def test_parse_last_checkpoint_picks_most_recent(tmp_path: Path) -> None:
    pdir = tmp_path / "profile"
    ckpt_dir = pdir / "checkpoints" / "session1"
    ckpt_dir.mkdir(parents=True)
    (ckpt_dir / "cp-old.json").write_text(
        json.dumps({"created_at": "2026-05-01T00:00:00Z"}), encoding="utf-8"
    )
    (ckpt_dir / "cp-new.json").write_text(
        json.dumps({"created_at": "2026-05-19T12:00:00Z"}), encoding="utf-8"
    )
    assert parse_timestamp("last-checkpoint", profile_dir=pdir) == _dt.datetime(
        2026, 5, 19, 12, 0, 0
    )


def test_parse_last_checkpoint_walks_across_sessions(tmp_path: Path) -> None:
    pdir = tmp_path / "profile"
    (pdir / "checkpoints" / "s1").mkdir(parents=True)
    (pdir / "checkpoints" / "s2").mkdir(parents=True)
    (pdir / "checkpoints" / "s1" / "cp-a.json").write_text(
        json.dumps({"created_at": "2026-05-01T00:00:00Z"}), encoding="utf-8"
    )
    (pdir / "checkpoints" / "s2" / "cp-b.json").write_text(
        json.dumps({"created_at": "2026-05-19T00:00:00Z"}), encoding="utf-8"
    )
    parsed = parse_timestamp("last-checkpoint", profile_dir=pdir)
    assert parsed == _dt.datetime(2026, 5, 19, 0, 0, 0)
