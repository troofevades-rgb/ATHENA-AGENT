"""Audit-log tests (T6-04.4).

The audit log captures every observe + input action with the
screenshot hash it was based on. JSONL appends, with screenshot
bytes EXCLUDED (only the SHA-256 lands in the log).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.computer.audit import (
    ActionAuditLog,
    default_audit_path,
    hash_screenshot,
)
from athena.computer.contract import Action, Screenshot


def _shot(payload: bytes = b"fake-pixels") -> Screenshot:
    return Screenshot(png_bytes=payload, width=100, height=80, scale=1.0)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def test_hash_screenshot_stable_and_sensitive():
    """Same bytes → same hash; one byte different → totally
    different hash. The audit log's correlation is only as good
    as this property."""
    a = hash_screenshot(_shot(b"AAAA"))
    b = hash_screenshot(_shot(b"AAAA"))
    c = hash_screenshot(_shot(b"AAAB"))
    assert a == b
    assert a != c
    assert len(a) == 64


def test_hash_empty_bytes():
    """An empty screenshot hashes deterministically too — no
    crash, no random salt."""
    h = hash_screenshot(_shot(b""))
    assert len(h) == 64


# ---------------------------------------------------------------------------
# Append + tail
# ---------------------------------------------------------------------------


def test_log_appends_jsonl(tmp_path: Path):
    log = ActionAuditLog(tmp_path / "audit.jsonl")
    log.log(
        action=Action(type="screenshot"),
        tier="observe",
        confirmed=None,
        executed=True,
        screenshot=_shot(),
        result="ok",
    )
    log.log(
        action=Action(
            type="click", target_desc="Delete", app="editor", coords=(100, 200)
        ),
        tier="destructive",
        confirmed=False,
        executed=False,
        screenshot=_shot(),
        result="denied",
    )
    raw = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(raw) == 2

    row1 = json.loads(raw[0])
    assert row1["type"] == "screenshot"
    assert row1["tier"] == "observe"
    assert row1["executed"] is True
    assert row1["result"] == "ok"
    assert "screenshot_sha256" in row1
    assert len(row1["screenshot_sha256"]) == 64

    row2 = json.loads(raw[1])
    assert row2["type"] == "click"
    assert row2["tier"] == "destructive"
    assert row2["target_desc"] == "Delete"
    assert row2["coords"] == [100, 200]
    assert row2["confirmed"] is False
    assert row2["executed"] is False
    assert row2["result"] == "denied"


def test_screenshot_bytes_NEVER_in_log(tmp_path: Path):
    """Critical: the audit log stores the HASH only, never the
    raw pixel bytes. (Pixel bytes can be megabytes per
    screenshot; the log would grow unboundedly.)"""
    payload = b"SUPER-SECRET-PIXELS-DO-NOT-LEAK-INTO-THE-LOG" * 100
    log = ActionAuditLog(tmp_path / "audit.jsonl")
    log.log(
        action=Action(type="screenshot"),
        tier="observe",
        confirmed=None,
        executed=True,
        screenshot=_shot(payload),
        result="ok",
    )
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "SUPER-SECRET-PIXELS-DO-NOT-LEAK" not in text


def test_tail_returns_latest(tmp_path: Path):
    log = ActionAuditLog(tmp_path / "audit.jsonl")
    for i in range(10):
        log.log(
            action=Action(type="screenshot"),
            tier="observe",
            confirmed=None,
            executed=True,
            screenshot=None,
            result=f"row-{i}",
        )
    out = log.tail(limit=3)
    assert len(out) == 3
    assert [e.result for e in out] == ["row-7", "row-8", "row-9"]


def test_tail_empty_when_no_file(tmp_path: Path):
    log = ActionAuditLog(tmp_path / "audit.jsonl")
    assert log.tail() == []


def test_tail_skips_malformed_rows(tmp_path: Path):
    """A corrupted log line shouldn't crash the status
    command — skip it cleanly."""
    log = ActionAuditLog(tmp_path / "audit.jsonl")
    log.log(
        action=Action(type="screenshot"),
        tier="observe",
        confirmed=None,
        executed=True,
        screenshot=None,
        result="ok",
    )
    # Manually corrupt a line.
    with open(tmp_path / "audit.jsonl", "a", encoding="utf-8") as f:
        f.write("not valid json {{{\n")
    out = log.tail()
    assert len(out) == 1  # the good row survived


# ---------------------------------------------------------------------------
# Default path resolution
# ---------------------------------------------------------------------------


def test_default_audit_path_uses_cfg_override(tmp_path: Path):
    from types import SimpleNamespace

    cfg = SimpleNamespace(computer_audit_path=str(tmp_path / "explicit.jsonl"))
    p = default_audit_path(cfg, tmp_path / "profile")
    assert p == tmp_path / "explicit.jsonl"


def test_default_audit_path_falls_back_to_profile_dir(tmp_path: Path):
    from types import SimpleNamespace

    cfg = SimpleNamespace(computer_audit_path=None)
    p = default_audit_path(cfg, tmp_path / "profile")
    assert p == tmp_path / "profile" / "computer_audit.jsonl"
