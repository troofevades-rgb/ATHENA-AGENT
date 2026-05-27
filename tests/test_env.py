"""Tests for the dotenv credential loader at ~/.athena/.env."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from athena import env as env_mod


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch):
    """Point the loader at a clean tmp .env file per-test, and reset
    its process-lifetime cache so state doesn't leak between cases."""
    fake_env = tmp_path / ".env"
    monkeypatch.setattr(env_mod, "_path", lambda: fake_env)
    env_mod.reset_cache()
    yield
    env_mod.reset_cache()


def _write_env(tmp_path: Path, body: str) -> Path:
    p = tmp_path / ".env"
    p.write_text(body, encoding="utf-8")
    return p


# ----------------------------------------------------------------------
# Parser — direct
# ----------------------------------------------------------------------


def test_parse_simple():
    assert env_mod._parse("FOO=bar\n") == {"FOO": "bar"}


def test_parse_blank_and_comment_lines_ignored():
    body = "\n# comment\nFOO=bar\n\n  # another\nBAZ=qux\n"
    assert env_mod._parse(body) == {"FOO": "bar", "BAZ": "qux"}


def test_parse_strips_double_quotes():
    assert env_mod._parse('FOO="bar baz"\n') == {"FOO": "bar baz"}


def test_parse_strips_single_quotes():
    assert env_mod._parse("FOO='bar baz'\n") == {"FOO": "bar baz"}


def test_parse_mismatched_quotes_preserved():
    """``FOO='bar"`` is suspect — leave it as-is rather than guessing."""
    assert env_mod._parse('FOO=\'bar"\n') == {"FOO": '\'bar"'}


def test_parse_handles_equals_in_value():
    """A value containing ``=`` (e.g. a JWT) is preserved."""
    body = "TOKEN=abc=def=ghi\n"
    assert env_mod._parse(body) == {"TOKEN": "abc=def=ghi"}


def test_parse_no_value_for_empty_key():
    body = "=novalue\n"
    assert env_mod._parse(body) == {}


def test_parse_later_overrides_earlier():
    body = "FOO=first\nFOO=second\n"
    assert env_mod._parse(body) == {"FOO": "second"}


# ----------------------------------------------------------------------
# load_dotenv — file I/O + cache
# ----------------------------------------------------------------------


def test_load_dotenv_missing_file_returns_empty(tmp_path: Path):
    assert env_mod.load_dotenv() == {}


def test_load_dotenv_reads_and_caches(tmp_path: Path):
    _write_env(tmp_path, "FOO=bar\n")
    out = env_mod.load_dotenv()
    assert out == {"FOO": "bar"}
    # Mutate the file; cached version stays.
    _write_env(tmp_path, "FOO=changed\n")
    assert env_mod.load_dotenv() == {"FOO": "bar"}


def test_reset_cache_picks_up_changes(tmp_path: Path):
    _write_env(tmp_path, "FOO=bar\n")
    env_mod.load_dotenv()
    _write_env(tmp_path, "FOO=changed\n")
    env_mod.reset_cache()
    assert env_mod.load_dotenv() == {"FOO": "changed"}


# ----------------------------------------------------------------------
# get_credential — lookup order
# ----------------------------------------------------------------------


def test_get_credential_from_dotenv(tmp_path: Path):
    _write_env(tmp_path, "ATHENA_XAI_API_KEY=xai-12345\n")
    assert env_mod.get_credential("ATHENA_XAI_API_KEY") == "xai-12345"


def test_get_credential_dotenv_wins_over_os_environ(tmp_path: Path, monkeypatch):
    _write_env(tmp_path, "ATHENA_FOO=from_file\n")
    monkeypatch.setenv("ATHENA_FOO", "from_env")
    assert env_mod.get_credential("ATHENA_FOO") == "from_file"


def test_get_credential_falls_back_to_os_environ(monkeypatch):
    """No .env entry → check os.environ."""
    monkeypatch.setenv("ATHENA_BAR", "from_env_only")
    assert env_mod.get_credential("ATHENA_BAR") == "from_env_only"


def test_get_credential_falls_back_to_file_path(tmp_path: Path):
    """Legacy ``*_path`` style — keep working."""
    legacy = tmp_path / "legacy_token.txt"
    legacy.write_text("legacy-token-value\n", encoding="utf-8")
    assert env_mod.get_credential(
        "ATHENA_LEGACY", fallback_path=str(legacy),
    ) == "legacy-token-value"


def test_get_credential_returns_default_when_all_miss():
    assert env_mod.get_credential("ATHENA_NOPE", default="fallback") == "fallback"


def test_get_credential_returns_none_when_no_default():
    assert env_mod.get_credential("ATHENA_NOPE") is None


def test_get_credential_empty_dotenv_value_falls_through(tmp_path: Path, monkeypatch):
    """An empty value in .env shouldn't shadow an os.environ that has one."""
    _write_env(tmp_path, "ATHENA_FOO=\n")
    monkeypatch.setenv("ATHENA_FOO", "env_value")
    assert env_mod.get_credential("ATHENA_FOO") == "env_value"


def test_get_credential_nonexistent_fallback_path_safe(tmp_path: Path):
    """A missing fallback file shouldn't crash — return None."""
    assert env_mod.get_credential(
        "ATHENA_NOPE", fallback_path=str(tmp_path / "does_not_exist"),
    ) is None
