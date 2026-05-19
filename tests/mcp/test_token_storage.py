"""On-disk token persistence — save / load / delete + permissions."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from athena.mcp import oauth


def _token(expires_in: int = 3600) -> oauth.StoredToken:
    return oauth.StoredToken(
        access_token="AT",
        refresh_token="RT",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        token_type="Bearer",
        scope="read",
    )


@pytest.fixture(autouse=True)
def isolated_tokens_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Point TOKENS_DIR at tmp_path so tests can't escape into the
    real ~/.athena/mcp_tokens/."""
    target = tmp_path / "mcp_tokens"
    monkeypatch.setattr(oauth, "TOKENS_DIR", target)
    return target


# ---- save / load round-trip ---------------------------------------


def test_save_and_load_round_trip(isolated_tokens_dir: Path) -> None:
    token = _token()
    oauth.save_token("server-1", token)
    loaded = oauth.load_token("server-1")
    assert loaded is not None
    assert loaded.access_token == "AT"
    assert loaded.refresh_token == "RT"
    assert loaded.token_type == "Bearer"
    assert loaded.scope == "read"
    # Datetime round-trips through ISO format.
    assert abs((loaded.expires_at - token.expires_at).total_seconds()) < 1.0


def test_load_returns_none_when_missing(isolated_tokens_dir: Path) -> None:
    assert oauth.load_token("never-saved") is None


def test_save_creates_parent_dir(isolated_tokens_dir: Path) -> None:
    """The tokens dir doesn't exist before first save."""
    assert not isolated_tokens_dir.exists()
    oauth.save_token("s", _token())
    assert isolated_tokens_dir.exists()


def test_save_is_atomic_no_tmp_file_left(isolated_tokens_dir: Path) -> None:
    oauth.save_token("s", _token())
    tmps = list(isolated_tokens_dir.glob("*.tmp"))
    assert tmps == []


@pytest.mark.skipif(sys.platform == "win32", reason="Windows ACLs replace POSIX permission bits")
def test_token_file_is_0600(isolated_tokens_dir: Path) -> None:
    oauth.save_token("s", _token())
    path = isolated_tokens_dir / "s.json"
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_save_overwrites_existing(isolated_tokens_dir: Path) -> None:
    oauth.save_token("s", _token())
    new = oauth.StoredToken(
        access_token="REPLACED",
        refresh_token="NEW",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    oauth.save_token("s", new)
    loaded = oauth.load_token("s")
    assert loaded.access_token == "REPLACED"
    assert loaded.refresh_token == "NEW"


# ---- defensive paths ----------------------------------------------


def test_save_rejects_path_traversal_in_server_id(
    isolated_tokens_dir: Path,
) -> None:
    """The server_id is constructed from mcp.json which the user
    controls — but we still defend against a malicious entry trying
    to write outside the tokens dir."""
    with pytest.raises(ValueError):
        oauth.save_token("../etc/passwd", _token())
    with pytest.raises(ValueError):
        oauth.save_token("a/b", _token())
    with pytest.raises(ValueError):
        oauth.save_token("a\\b", _token())


def test_save_rejects_empty_server_id(isolated_tokens_dir: Path) -> None:
    with pytest.raises(ValueError):
        oauth.save_token("", _token())


def test_load_returns_none_for_malformed_json(
    isolated_tokens_dir: Path,
) -> None:
    isolated_tokens_dir.mkdir(parents=True)
    (isolated_tokens_dir / "broken.json").write_text("not json", encoding="utf-8")
    assert oauth.load_token("broken") is None


def test_load_returns_none_for_missing_required_field(
    isolated_tokens_dir: Path,
) -> None:
    isolated_tokens_dir.mkdir(parents=True)
    (isolated_tokens_dir / "partial.json").write_text(
        json.dumps({"refresh_token": "x"}),
        encoding="utf-8",
    )
    assert oauth.load_token("partial") is None


# ---- delete -------------------------------------------------------


def test_delete_token_removes_file(isolated_tokens_dir: Path) -> None:
    oauth.save_token("s", _token())
    assert oauth.delete_token("s") is True
    assert (isolated_tokens_dir / "s.json").exists() is False
    assert oauth.load_token("s") is None


def test_delete_token_returns_false_when_missing(
    isolated_tokens_dir: Path,
) -> None:
    assert oauth.delete_token("ghost") is False


# ---- list_token_status ------------------------------------------


def test_list_token_status_empty(isolated_tokens_dir: Path) -> None:
    assert oauth.list_token_status() == {}


def test_list_token_status_returns_all_servers(
    isolated_tokens_dir: Path,
) -> None:
    oauth.save_token("linear", _token(expires_in=7200))
    oauth.save_token("sentry", _token(expires_in=600))
    status = oauth.list_token_status()
    assert set(status.keys()) == {"linear", "sentry"}
    assert status["linear"]["expires_in_seconds"] > status["sentry"]["expires_in_seconds"]
    assert status["linear"]["scope"] == "read"
    assert status["linear"]["has_refresh_token"] is True


def test_list_token_status_skips_unparseable(
    isolated_tokens_dir: Path,
) -> None:
    oauth.save_token("good", _token())
    isolated_tokens_dir.mkdir(parents=True, exist_ok=True)
    (isolated_tokens_dir / "bad.json").write_text("invalid", encoding="utf-8")
    status = oauth.list_token_status()
    assert "good" in status
    assert "bad" not in status
