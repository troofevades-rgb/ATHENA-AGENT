"""Gateway credential resolver tests.

Pins the same shape the X bearer-token migration pins, applied
across every gateway secret:

  - <key>_path beats cleartext when both present
  - file path → stripped contents returned
  - empty file → falls back to cleartext (with warning)
  - cleartext fallback fires a one-shot deprecation warning
    per (platform, key) pair (the rotation nudge)
  - missing both → ValueError naming both shapes (when
    required=True)
  - missing both + required=False → None
  - the secret NEVER appears in any log line
  - one-shot semantics: the deprecation warning fires once
    per (platform, key), even on flapping reconnects
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from athena.gateway.credentials import (
    _reset_warning_memo_for_tests,
    resolve_credential,
)


@pytest.fixture(autouse=True)
def _reset_memo():
    """Each test starts with a fresh one-shot warning memo."""
    _reset_warning_memo_for_tests()
    yield
    _reset_warning_memo_for_tests()


# ---------------------------------------------------------------
# file path wins
# ---------------------------------------------------------------


def test_path_returns_file_contents(tmp_path: Path):
    p = tmp_path / "tok.txt"
    p.write_text("FILE-TOKEN", encoding="utf-8")
    out = resolve_credential(
        {"bot_token_path": str(p)},
        "bot_token",
        platform="discord",
    )
    assert out == "FILE-TOKEN"


def test_path_strips_trailing_whitespace(tmp_path: Path):
    p = tmp_path / "tok.txt"
    p.write_text("FILE-TOKEN\n\n  \r\n", encoding="utf-8")
    assert resolve_credential(
        {"bot_token_path": str(p)},
        "bot_token",
        platform="discord",
    ) == "FILE-TOKEN"


def test_path_wins_over_cleartext(tmp_path: Path):
    p = tmp_path / "tok.txt"
    p.write_text("FROM-FILE", encoding="utf-8")
    out = resolve_credential(
        {
            "bot_token_path": str(p),
            "bot_token": "FROM-CLEARTEXT",
        },
        "bot_token",
        platform="discord",
    )
    assert out == "FROM-FILE"


def test_path_handles_tilde_expansion(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    p = tmp_path / "discord_token.txt"
    p.write_text("HOMEDIR-TOK", encoding="utf-8")
    out = resolve_credential(
        {"bot_token_path": "~/discord_token.txt"},
        "bot_token",
        platform="discord",
    )
    assert out == "HOMEDIR-TOK"


# ---------------------------------------------------------------
# cleartext fallback + one-shot deprecation warning
# ---------------------------------------------------------------


def test_cleartext_fallback_returns_value(caplog):
    caplog.set_level(logging.WARNING, logger="athena.gateway.credentials")
    out = resolve_credential(
        {"bot_token": "CLEARTEXT-TOK"},
        "bot_token",
        platform="discord",
    )
    assert out == "CLEARTEXT-TOK"
    # Warning fired naming the migration path.
    assert any(
        "discord.bot_token is configured as cleartext" in r.getMessage()
        for r in caplog.records
    )


def test_cleartext_deprecation_fires_only_once_per_pair(caplog):
    caplog.set_level(logging.WARNING, logger="athena.gateway.credentials")
    for _ in range(5):
        resolve_credential(
            {"bot_token": "TOK"},
            "bot_token",
            platform="discord",
        )
    nudges = [
        r for r in caplog.records
        if "discord.bot_token is configured as cleartext" in r.getMessage()
    ]
    assert len(nudges) == 1


def test_different_platforms_warn_independently(caplog):
    caplog.set_level(logging.WARNING, logger="athena.gateway.credentials")
    resolve_credential({"bot_token": "T1"}, "bot_token", platform="discord")
    resolve_credential({"bot_token": "T2"}, "bot_token", platform="slack")
    resolve_credential({"bot_token": "T3"}, "bot_token", platform="telegram")
    # Three separate one-shot warnings.
    msgs = [r.getMessage() for r in caplog.records]
    assert sum("discord.bot_token" in m for m in msgs) == 1
    assert sum("slack.bot_token" in m for m in msgs) == 1
    assert sum("telegram.bot_token" in m for m in msgs) == 1


def test_different_keys_warn_independently(caplog):
    caplog.set_level(logging.WARNING, logger="athena.gateway.credentials")
    resolve_credential(
        {"bot_token": "B", "app_token": "A"},
        "bot_token", platform="slack",
    )
    resolve_credential(
        {"bot_token": "B", "app_token": "A"},
        "app_token", platform="slack",
    )
    msgs = [r.getMessage() for r in caplog.records]
    assert sum("slack.bot_token" in m for m in msgs) == 1
    assert sum("slack.app_token" in m for m in msgs) == 1


# ---------------------------------------------------------------
# fallback chain
# ---------------------------------------------------------------


def test_missing_file_falls_back_to_cleartext(tmp_path: Path, caplog):
    caplog.set_level(logging.WARNING, logger="athena.gateway.credentials")
    out = resolve_credential(
        {
            "bot_token_path": str(tmp_path / "nope.txt"),
            "bot_token": "FALLBACK",
        },
        "bot_token",
        platform="discord",
    )
    assert out == "FALLBACK"


def test_empty_file_falls_back_to_cleartext(tmp_path: Path, caplog):
    caplog.set_level(logging.WARNING, logger="athena.gateway.credentials")
    p = tmp_path / "empty.txt"
    p.write_text("   \n\n", encoding="utf-8")
    out = resolve_credential(
        {
            "bot_token_path": str(p),
            "bot_token": "FALLBACK",
        },
        "bot_token",
        platform="discord",
    )
    assert out == "FALLBACK"
    # The empty-file warning fires.
    assert any(
        "is empty" in r.getMessage() for r in caplog.records
    )


# ---------------------------------------------------------------
# missing both
# ---------------------------------------------------------------


def test_missing_both_required_raises():
    with pytest.raises(ValueError, match="bot_token") as exc:
        resolve_credential({}, "bot_token", platform="discord")
    msg = str(exc.value)
    # The error names BOTH shapes so the operator knows what to fix.
    assert "bot_token_path" in msg
    assert "discord" in msg


def test_missing_both_optional_returns_none():
    out = resolve_credential(
        {}, "bot_token", platform="discord", required=False,
    )
    assert out is None


def test_missing_both_with_only_cleartext_fallback_handles_blank():
    """Empty string in the cleartext slot doesn't count as
    present — same as missing both."""
    with pytest.raises(ValueError):
        resolve_credential(
            {"bot_token": ""},
            "bot_token",
            platform="discord",
        )


# ---------------------------------------------------------------
# never-in-logs
# ---------------------------------------------------------------


def test_token_never_in_logs_via_path(tmp_path: Path, caplog):
    """Full DEBUG capture across the file-path branch — the
    token bytes must NOT appear in the log."""
    p = tmp_path / "tok.txt"
    p.write_text("VERY-SECRET-ABC123XYZ", encoding="utf-8")
    caplog.set_level(logging.DEBUG, logger="athena.gateway.credentials")
    resolve_credential(
        {"bot_token_path": str(p)},
        "bot_token",
        platform="discord",
    )
    assert "VERY-SECRET-ABC123XYZ" not in caplog.text
    # The length-only marker IS present (operator can verify
    # the file was read without knowing the value).
    assert "len=21" in caplog.text


def test_token_never_in_logs_via_cleartext(caplog):
    """Full DEBUG capture across the cleartext branch — the
    deprecation warning names the key + the migration path,
    NOT the value."""
    caplog.set_level(logging.DEBUG, logger="athena.gateway.credentials")
    resolve_credential(
        {"bot_token": "VERY-SECRET-CLEARTEXT-ZZ9"},
        "bot_token",
        platform="discord",
    )
    assert "VERY-SECRET-CLEARTEXT-ZZ9" not in caplog.text
