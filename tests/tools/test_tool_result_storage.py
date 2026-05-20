"""Tests for athena.tools.tool_result_storage (T2-06.3)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from athena.tools.tool_result_storage import (
    HANDLE_RE,
    ToolResultStorage,
    maybe_store_result,
)


@pytest.fixture
def storage(tmp_path: Path) -> ToolResultStorage:
    return ToolResultStorage(tmp_path / "tool_results", session_id="test-session")


# ---------------------------------------------------------------------------
# Threshold
# ---------------------------------------------------------------------------


def test_store_small_inline_under_threshold(storage: ToolResultStorage) -> None:
    content = "x" * 100
    result = maybe_store_result(
        content=content,
        tool_name="shell",
        threshold_bytes=1_000_000,
        storage=storage,
    )
    assert result == content


def test_store_large_returns_handle(storage: ToolResultStorage) -> None:
    content = "x" * 2_000_000  # 2MB
    result = maybe_store_result(
        content=content,
        tool_name="shell",
        threshold_bytes=1_000_000,
        storage=storage,
    )
    match = HANDLE_RE.search(result)
    assert match is not None
    digest = match.group(1)
    assert (storage.storage_dir / f"{digest}.txt").exists()


# ---------------------------------------------------------------------------
# Idempotence + identity
# ---------------------------------------------------------------------------


def test_idempotent_storage(storage: ToolResultStorage) -> None:
    """Same content stored twice -> same hash, same blob."""
    content = "y" * 2_000_000
    r1 = storage.store(content, tool_name="shell")
    r2 = storage.store(content, tool_name="shell")
    assert r1.hash == r2.hash
    assert r1.path == r2.path


def test_different_content_different_hash(storage: ToolResultStorage) -> None:
    r1 = storage.store("alpha" * 200_000, tool_name="shell")
    r2 = storage.store("bravo" * 200_000, tool_name="shell")
    assert r1.hash != r2.hash
    assert r1.path != r2.path


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def test_read_full_blob(storage: ToolResultStorage) -> None:
    content = "hello world " * 100_000  # ~1.2MB
    stored = storage.store(content, tool_name="shell")
    result = storage.read(stored.handle, max_bytes=len(content), offset=0)
    assert result == content


def test_read_partial_with_offset(storage: ToolResultStorage) -> None:
    content = "0123456789" * 100_000
    stored = storage.store(content, tool_name="shell")
    result = storage.read(stored.handle, max_bytes=10, offset=20)
    assert result == "0123456789"


def test_read_by_bare_hash(storage: ToolResultStorage) -> None:
    content = "z" * 2_000_000
    stored = storage.store(content, tool_name="shell")
    result = storage.read(stored.hash, max_bytes=100, offset=0)
    assert result.startswith("zzz")


def test_read_by_bare_prefixed_form(storage: ToolResultStorage) -> None:
    """``tool_result:<hash>`` (sans the bracketed wrapper) also resolves."""
    content = "q" * 2_000_000
    stored = storage.store(content, tool_name="shell")
    raw = f"tool_result:{stored.hash}"
    result = storage.read(raw, max_bytes=10, offset=0)
    assert result == "qqqqqqqqqq"


def test_read_invalid_handle_raises(storage: ToolResultStorage) -> None:
    with pytest.raises(ValueError):
        storage.read("not a handle at all", max_bytes=100, offset=0)


def test_read_missing_blob_raises(storage: ToolResultStorage) -> None:
    with pytest.raises(FileNotFoundError):
        storage.read("0000000000000000", max_bytes=100, offset=0)


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


def test_index_appends_one_line_per_store(storage: ToolResultStorage) -> None:
    storage.store("a" * 2_000_000, tool_name="shell")
    storage.store("b" * 2_000_000, tool_name="bash")
    lines = storage.index_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    import json as _json

    parsed = [_json.loads(line) for line in lines]
    assert parsed[0]["tool"] == "shell"
    assert parsed[1]["tool"] == "bash"
    assert parsed[0]["session_id"] == "test-session"


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def test_cleanup_removes_unreferenced_old_blobs(storage: ToolResultStorage, tmp_path: Path) -> None:
    content = "old " * 500_000  # ~2MB
    stored = storage.store(content, tool_name="shell")
    long_ago = time.time() - 60 * 86400  # 60 days
    os.utime(stored.path, (long_ago, long_ago))

    empty_session = tmp_path / "session.jsonl"
    empty_session.write_text('{"role":"user","content":"hi"}\n')

    summary = storage.cleanup_unreferenced(
        session_log_paths=[empty_session],
        older_than_days=30,
    )
    assert summary["blobs_removed"] == 1
    assert not stored.path.exists()


def test_cleanup_preserves_referenced_blob(storage: ToolResultStorage, tmp_path: Path) -> None:
    content = "ref " * 500_000
    stored = storage.store(content, tool_name="shell")
    long_ago = time.time() - 60 * 86400
    os.utime(stored.path, (long_ago, long_ago))

    session = tmp_path / "session.jsonl"
    session.write_text(f'{{"role":"tool","content":"{stored.handle}"}}\n')

    summary = storage.cleanup_unreferenced(
        session_log_paths=[session],
        older_than_days=30,
    )
    assert summary["blobs_removed"] == 0
    assert stored.path.exists()


def test_cleanup_preserves_recent_unreferenced(storage: ToolResultStorage, tmp_path: Path) -> None:
    """Recent blobs are kept regardless of reference status."""
    content = "recent " * 500_000
    stored = storage.store(content, tool_name="shell")
    # Don't backdate; mtime is now.

    empty_session = tmp_path / "session.jsonl"
    empty_session.write_text("{}\n")

    summary = storage.cleanup_unreferenced(
        session_log_paths=[empty_session],
        older_than_days=30,
    )
    assert summary["blobs_removed"] == 0
    assert stored.path.exists()


def test_cleanup_dry_run_counts_but_does_not_delete(
    storage: ToolResultStorage, tmp_path: Path
) -> None:
    content = "dry " * 500_000
    stored = storage.store(content, tool_name="shell")
    long_ago = time.time() - 60 * 86400
    os.utime(stored.path, (long_ago, long_ago))

    empty_session = tmp_path / "session.jsonl"
    empty_session.write_text("{}\n")

    summary = storage.cleanup_unreferenced(
        session_log_paths=[empty_session],
        older_than_days=30,
        dry_run=True,
    )
    assert summary["blobs_removed"] == 1
    assert summary["bytes_freed"] > 0
    # File still exists because dry_run=True.
    assert stored.path.exists()


def test_cleanup_picks_up_bare_hash_references(storage: ToolResultStorage, tmp_path: Path) -> None:
    """A session log containing ``tool_result:<hash>`` (no bracket)
    still counts as a reference."""
    content = "bare-ref " * 200_000
    stored = storage.store(content, tool_name="shell")
    long_ago = time.time() - 60 * 86400
    os.utime(stored.path, (long_ago, long_ago))

    session = tmp_path / "session.jsonl"
    session.write_text(
        f'{{"role":"assistant","content":"see tool_result:{stored.hash} for more"}}\n'
    )

    summary = storage.cleanup_unreferenced(
        session_log_paths=[session],
        older_than_days=30,
    )
    assert summary["blobs_removed"] == 0
