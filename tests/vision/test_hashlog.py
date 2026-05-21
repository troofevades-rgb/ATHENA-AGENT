"""T4-01.2 — sha256_file + HashLogger tests.

Invariants pinned:

  - sha256_file matches a hand-computed digest on bytes-level
    fixtures (catches "we forgot to update the rolling hash").
  - HashLogger.log appends one well-formed JSONL row.
  - Multiple log calls produce ordered rows.
  - Parent dir is created lazily on first append.
  - tail() reads what log() wrote, in order.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from athena.vision.hashlog import (
    HashLogEntry,
    HashLogger,
    audit_path,
    sha256_file,
)
from tests.vision.fixtures import FIXTURES_DIR, ensure_fixtures


def test_sha256_file_matches_manual(tmp_path: Path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"hello, vision provenance")
    expected = hashlib.sha256(b"hello, vision provenance").hexdigest()
    assert sha256_file(p) == expected


def test_sha256_file_streams_in_chunks(tmp_path: Path):
    """Force a chunk boundary mid-file to prove the streaming
    accumulator isn't broken on multi-chunk reads."""
    p = tmp_path / "big.bin"
    payload = b"abcdefgh" * 50_000  # 400 KB
    p.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    assert sha256_file(p, chunk_size=4096) == expected


def test_sha256_file_on_fixture():
    ensure_fixtures()
    orig = FIXTURES_DIR / "original.jpg"
    h = sha256_file(orig)
    # Recompute by hand to prove the helper matches reality.
    assert h == hashlib.sha256(orig.read_bytes()).hexdigest()
    assert len(h) == 64  # hex


def test_sha256_file_missing_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        sha256_file(tmp_path / "nope.bin")


def test_hashlog_appends_one_row(tmp_path: Path):
    log = HashLogger(audit_path(tmp_path))
    entry = log.log(
        mode="describe",
        path="/tmp/foo.png",
        sha256="a" * 64,
        size_bytes=12345,
    )
    assert isinstance(entry, HashLogEntry)
    raw = (tmp_path / "vision_audit.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    assert len(rows) == 1
    r = rows[0]
    assert r["mode"] == "describe"
    assert r["path"] == "/tmp/foo.png"
    assert r["sha256"] == "a" * 64
    assert r["bytes"] == 12345
    # ts is ISO-8601 UTC with 'Z' suffix
    assert r["ts"].endswith("Z")
    # No `extra` key when none was supplied.
    assert "extra" not in r


def test_hashlog_extra_round_trips(tmp_path: Path):
    log = HashLogger(audit_path(tmp_path))
    log.log(
        mode="ela",
        path="/tmp/x.jpg",
        sha256="b" * 64,
        size_bytes=1024,
        extra={"quality": 80, "patches": 3},
    )
    raw = (tmp_path / "vision_audit.jsonl").read_text(encoding="utf-8")
    row = json.loads(raw.splitlines()[0])
    assert row["extra"] == {"quality": 80, "patches": 3}


def test_hashlog_multiple_rows_ordered(tmp_path: Path):
    log = HashLogger(audit_path(tmp_path))
    for i in range(5):
        log.log(
            mode="describe", path=f"/tmp/f{i}.png",
            sha256=str(i) * 64, size_bytes=100 + i,
        )
    tailed = log.tail()
    assert [e.path for e in tailed] == [f"/tmp/f{i}.png" for i in range(5)]
    assert [e.bytes for e in tailed] == [100, 101, 102, 103, 104]


def test_hashlog_parent_dir_created_lazily(tmp_path: Path):
    nested = tmp_path / "deep" / "nested" / "profile"
    log = HashLogger(audit_path(nested))
    assert not nested.exists()
    log.log(mode="phash", path="/p", sha256="c" * 64, size_bytes=1)
    assert (nested / "vision_audit.jsonl").exists()


def test_hashlog_tail_handles_missing_file(tmp_path: Path):
    log = HashLogger(audit_path(tmp_path / "fresh"))
    assert log.tail() == []


def test_hashlog_tail_skips_malformed_lines(tmp_path: Path):
    p = audit_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"ts":"2026-01-01T00:00:00Z","mode":"describe","path":"/a","sha256":"00","bytes":1}\n'
        "this is not json\n"
        '{"ts":"2026-01-01T00:00:01Z","mode":"exif","path":"/b","sha256":"11","bytes":2}\n',
        encoding="utf-8",
    )
    log = HashLogger(p)
    entries = log.tail()
    assert [e.path for e in entries] == ["/a", "/b"]
