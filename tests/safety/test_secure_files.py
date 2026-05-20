"""Tests for athena.safety.secure_files.

Goal: prove that no window exists where a credential file is at any
mode wider than 0o600, even under concurrent fork.

Mode-specific assertions are skipped on Windows because the POSIX
mode model doesn't apply there (Windows ``chmod`` only toggles the
read-only bit). CI exercises the full assertion set on Linux runners
per the T1-01 matrix.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
from pathlib import Path

import pytest

from athena.safety.secure_files import (
    ensure_secure_dir,
    secure_read_json,
    secure_read_text,
    secure_write_json,
    secure_write_text,
)

posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX mode semantics don't apply on Windows",
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@posix_only
def test_secure_write_text_creates_at_0o600(tmp_path: Path) -> None:
    target = tmp_path / "creds.txt"
    secure_write_text(target, "hello")
    assert target.read_text() == "hello"
    assert _mode(target) == 0o600


@posix_only
def test_secure_write_replaces_existing_atomically(tmp_path: Path) -> None:
    target = tmp_path / "creds.txt"
    secure_write_text(target, "v1")
    secure_write_text(target, "v2")
    assert target.read_text() == "v2"
    assert _mode(target) == 0o600


def test_secure_write_leaves_no_tmp_files(tmp_path: Path) -> None:
    target = tmp_path / "creds.txt"
    secure_write_text(target, "hello")
    siblings = list(tmp_path.iterdir())
    assert siblings == [target], f"unexpected sibling files: {siblings}"


def test_secure_write_json_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "creds.json"
    payload = {"key": "value", "list": [1, 2, 3]}
    secure_write_json(target, payload)
    assert secure_read_json(target) == payload


def test_secure_write_json_is_deterministic(tmp_path: Path) -> None:
    """sort_keys=True + compact separators give content-addressable output."""
    target = tmp_path / "creds.json"
    secure_write_json(target, {"b": 2, "a": 1})
    raw = target.read_text(encoding="utf-8")
    assert raw == '{"a":1,"b":2}'


def test_secure_write_under_concurrent_threads(tmp_path: Path) -> None:
    """50 threads writing the same path produce exactly one consistent file."""
    target = tmp_path / "creds.json"

    def worker(i: int) -> None:
        secure_write_json(target, {"i": i})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    payload = secure_read_json(target)
    assert isinstance(payload, dict) and "i" in payload
    assert isinstance(payload["i"], int)
    assert 0 <= payload["i"] < 50
    if sys.platform != "win32":
        assert _mode(target) == 0o600

    siblings = [p for p in tmp_path.iterdir() if p != target]
    assert siblings == [], f"leftover temp files after concurrent writes: {siblings}"


@posix_only
def test_secure_write_never_exists_at_wider_mode(tmp_path: Path) -> None:
    """End state must be 0o600 — proves we didn't widen via the temp dance."""
    target = tmp_path / "creds.txt"
    secure_write_text(target, "hello")
    assert _mode(target) == 0o600


@posix_only
def test_secure_read_warns_on_wide_mode(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    target = tmp_path / "creds.txt"
    target.write_text("hello")
    os.chmod(target, 0o644)
    with caplog.at_level("WARNING"):
        text = secure_read_text(target)
    assert text == "hello"
    assert any("0o644" in r.message for r in caplog.records)


@posix_only
def test_ensure_secure_dir_creates_at_0o700(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir"
    ensure_secure_dir(target)
    assert target.is_dir()
    assert _mode(target) == 0o700


@posix_only
def test_ensure_secure_dir_warns_on_existing_wide_mode(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    target = tmp_path / "wide"
    target.mkdir(mode=0o755)
    with caplog.at_level("WARNING"):
        ensure_secure_dir(target)
    assert any("0o755" in r.message for r in caplog.records)


@posix_only
def test_ensure_secure_dir_dedups_repeated_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The credential-pool _save path calls ensure_secure_dir twice
    (once explicitly, once via secure_write_text). The warning must
    fire EXACTLY ONCE per (process, path) — not once per call site."""
    from athena.safety.secure_files import _warned_wide_dirs

    _warned_wide_dirs.clear()
    target = tmp_path / "wide2"
    target.mkdir(mode=0o755)
    with caplog.at_level("WARNING"):
        ensure_secure_dir(target)
        ensure_secure_dir(target)
        ensure_secure_dir(target)
    warnings = [r for r in caplog.records if "0o755" in r.message]
    assert len(warnings) == 1, (
        f"expected 1 warning, got {len(warnings)}: {[r.message for r in warnings]}"
    )


@posix_only
def test_secure_write_handles_unwritable_temp(tmp_path: Path) -> None:
    """If we can't create the temp file, raise PermissionError cleanly."""
    target = tmp_path / "creds.txt"
    os.chmod(tmp_path, 0o500)
    try:
        with pytest.raises(PermissionError):
            secure_write_text(target, "hello")
        assert not target.exists()
    finally:
        os.chmod(tmp_path, 0o700)


def test_secure_read_json_parses_dict(tmp_path: Path) -> None:
    target = tmp_path / "creds.json"
    secure_write_json(target, {"a": 1})
    assert secure_read_json(target) == {"a": 1}


def test_secure_write_text_unicode(tmp_path: Path) -> None:
    target = tmp_path / "creds.txt"
    secure_write_text(target, "héllo — ✓")
    assert target.read_text(encoding="utf-8") == "héllo — ✓"


def test_secure_write_json_uses_separators(tmp_path: Path) -> None:
    """No whitespace padding — compact representation."""
    target = tmp_path / "creds.json"
    secure_write_json(target, {"x": [1, 2, 3]})
    raw = target.read_text(encoding="utf-8")
    assert raw == '{"x":[1,2,3]}'
    parsed = json.loads(raw)
    assert parsed == {"x": [1, 2, 3]}
