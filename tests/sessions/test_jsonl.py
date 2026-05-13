"""Tests for ocode.sessions.jsonl."""
from __future__ import annotations

import logging
from pathlib import Path

from ocode.sessions.jsonl import append_jsonl, count_lines, read_jsonl


def test_jsonl_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello", "tool_calls": [{"function": {"name": "x"}}]},
        {"role": "tool", "name": "x", "content": "result"},
    ]
    for m in messages:
        append_jsonl(path, m)
    read_back = list(read_jsonl(path))
    assert read_back == messages
    assert count_lines(path) == 3


def test_jsonl_handles_unicode(tmp_path: Path) -> None:
    path = tmp_path / "u.jsonl"
    msg = {"role": "user", "content": "日本語と emoji 🚀"}
    append_jsonl(path, msg)
    [read_back] = list(read_jsonl(path))
    assert read_back == msg


def test_jsonl_skips_malformed_lines_with_warning(
    tmp_path: Path, caplog
) -> None:
    path = tmp_path / "m.jsonl"
    # Write a mixed file: valid, broken, valid.
    path.write_text(
        '{"role": "user", "content": "ok1"}\n'
        '{this is not json\n'
        '{"role": "user", "content": "ok2"}\n',
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="ocode.sessions.jsonl"):
        rows = list(read_jsonl(path))
    contents = [r["content"] for r in rows]
    assert contents == ["ok1", "ok2"]
    assert any("malformed" in rec.message for rec in caplog.records)


def test_read_missing_file_yields_nothing(tmp_path: Path) -> None:
    assert list(read_jsonl(tmp_path / "no.jsonl")) == []
    assert count_lines(tmp_path / "no.jsonl") == 0


def test_append_creates_parents(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deeper" / "s.jsonl"
    append_jsonl(path, {"role": "user", "content": "x"})
    assert path.exists()
    assert path.parent.is_dir()


def test_fsync_env_path_does_not_corrupt(tmp_path: Path, monkeypatch) -> None:
    """Just exercise the fsync branch — we can't easily assert fsync happened,
    but we can confirm the data round-trips with the flag on."""
    monkeypatch.setenv("OCODE_SESSIONS_FSYNC", "1")
    path = tmp_path / "f.jsonl"
    append_jsonl(path, {"a": 1})
    [row] = list(read_jsonl(path))
    assert row == {"a": 1}
