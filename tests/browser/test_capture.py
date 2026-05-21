"""T4-03.3 — capture log + politeness throttle tests."""

from __future__ import annotations

import json
from pathlib import Path

from athena.browser.capture import CaptureLogger


# ---------------------------------------------------------------
# capture log
# ---------------------------------------------------------------


def test_log_appends_jsonl_row(tmp_path: Path):
    cl = CaptureLogger(tmp_path / "browser_capture.jsonl")
    entry = cl.log(
        session_id="s1",
        url="https://example.com/",
        final_url="https://example.com/",
        status=200,
        title="Example",
        content="<html>...</html>",
    )
    assert entry["url"] == "https://example.com/"
    assert entry["session_id"] == "s1"
    raw = (tmp_path / "browser_capture.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(l) for l in raw.splitlines() if l.strip()]
    assert len(rows) == 1
    r = rows[0]
    assert r["status"] == 200
    assert r["title"] == "Example"
    # content_sha256 is a 64-char hex digest of the page content.
    assert len(r["content_sha256"]) == 64


def test_log_empty_content_hash_when_no_content(tmp_path: Path):
    cl = CaptureLogger(tmp_path / "browser_capture.jsonl")
    cl.log(
        session_id="s1",
        url="https://example.com/",
        final_url="https://example.com/",
        status=200,
        title="Example",
        # no content arg
    )
    rows = [json.loads(l) for l in (tmp_path / "browser_capture.jsonl").read_text().splitlines() if l.strip()]
    assert rows[0]["content_sha256"] == ""


def test_log_parent_dir_created_lazily(tmp_path: Path):
    nested = tmp_path / "deep" / "nested" / "browser_capture.jsonl"
    cl = CaptureLogger(nested)
    assert not nested.parent.exists()
    cl.log(session_id="s", url="u", final_url="u", status=0,
           title="t", content="x")
    assert nested.exists()


def test_log_status_none_recorded_as_zero(tmp_path: Path):
    cl = CaptureLogger(tmp_path / "c.jsonl")
    cl.log(session_id="s", url="u", final_url="u", status=None,
           title="t", content="")
    rows = [json.loads(l) for l in (tmp_path / "c.jsonl").read_text().splitlines() if l.strip()]
    assert rows[0]["status"] == 0


def test_tail_returns_recent_entries(tmp_path: Path):
    cl = CaptureLogger(tmp_path / "c.jsonl")
    for i in range(5):
        cl.log(session_id="s", url=f"u{i}", final_url=f"u{i}",
               status=200, title=f"t{i}", content="")
    tailed = cl.tail()
    assert [t["url"] for t in tailed] == [f"u{i}" for i in range(5)]


def test_tail_handles_missing_file(tmp_path: Path):
    cl = CaptureLogger(tmp_path / "fresh.jsonl")
    assert cl.tail() == []


def test_tail_skips_malformed_lines(tmp_path: Path):
    p = tmp_path / "c.jsonl"
    p.write_text(
        '{"url":"a"}\nnot-json\n{"url":"b"}\n',
        encoding="utf-8",
    )
    cl = CaptureLogger(p)
    assert [e["url"] for e in cl.tail()] == ["a", "b"]


# ---------------------------------------------------------------
# politeness throttle
# ---------------------------------------------------------------


def test_throttle_sleeps_within_interval(tmp_path: Path):
    sleeps: list[float] = []
    cl = CaptureLogger(
        tmp_path / "c.jsonl",
        min_interval_s=1.0,
        sleep_fn=lambda s: sleeps.append(s),
    )
    cl.throttle("https://example.com/a")  # first nav — no sleep
    cl.throttle("https://example.com/b")  # same domain immediately — sleep
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 1.0


def test_throttle_no_sleep_across_different_domains(tmp_path: Path):
    sleeps: list[float] = []
    cl = CaptureLogger(
        tmp_path / "c.jsonl",
        min_interval_s=1.0,
        sleep_fn=lambda s: sleeps.append(s),
    )
    cl.throttle("https://example.com/a")
    cl.throttle("https://other.com/a")
    # Two distinct domains — no sleep.
    assert sleeps == []


def test_throttle_no_sleep_when_interval_elapsed(tmp_path: Path, monkeypatch):
    """Force time.monotonic to advance past min_interval — no
    sleep should fire on the second call."""
    sleeps: list[float] = []
    cl = CaptureLogger(
        tmp_path / "c.jsonl",
        min_interval_s=1.0,
        sleep_fn=lambda s: sleeps.append(s),
    )
    cl.throttle("https://example.com/a")
    # Hack the in-memory last-nav stamp far enough back to
    # bypass the wait window.
    cl._last_nav_by_domain["example.com"] -= 10.0
    cl.throttle("https://example.com/b")
    assert sleeps == []


def test_throttle_disabled_when_zero_interval(tmp_path: Path):
    sleeps: list[float] = []
    cl = CaptureLogger(
        tmp_path / "c.jsonl",
        min_interval_s=0,
        sleep_fn=lambda s: sleeps.append(s),
    )
    cl.throttle("https://example.com/a")
    cl.throttle("https://example.com/b")
    cl.throttle("https://example.com/c")
    assert sleeps == []


def test_throttle_handles_invalid_url(tmp_path: Path):
    """A bad URL shouldn't crash the throttle — just no-op."""
    cl = CaptureLogger(tmp_path / "c.jsonl", min_interval_s=1.0)
    cl.throttle("not a url")  # must not raise
