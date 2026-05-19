"""``athena mcp`` CLI subcommands."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from athena.cli import mcp as cli
from athena.mcp import oauth


@pytest.fixture(autouse=True)
def isolated_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "mcp_tokens"
    monkeypatch.setattr(oauth, "TOKENS_DIR", target)
    return target


def _write_mcp_json(tmp_path: Path, payload: dict) -> Path:
    """Write a temp mcp.json under tmp_path and point the CLI's
    config-path discovery there."""
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


@pytest.fixture
def monkey_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point cwd-derived mcp_config_paths at tmp_path so the workspace
    file becomes our test fixture."""
    monkeypatch.chdir(tmp_path)
    # Also make sure user-level mcp.json doesn't pollute.
    from athena import config as cfg_mod

    monkeypatch.setattr(
        cfg_mod,
        "USER_MCP_PATH",
        tmp_path / "nonexistent" / "mcp.json",
    )
    return tmp_path


# ---- list ---------------------------------------------------------


def test_list_empty(monkey_cwd: Path, capsys: pytest.CaptureFixture) -> None:
    rc = cli.main(["list"])
    assert rc == 0
    assert "(no mcp servers configured)" in capsys.readouterr().out


def test_list_shows_stdio_and_sse(
    monkey_cwd: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write_mcp_json(
        monkey_cwd,
        {
            "mcpServers": {
                "local-fs": {"command": "npx", "args": ["fs-server"]},
                "linear": {
                    "transport": "sse",
                    "url": "https://mcp.linear.app/sse",
                    "oauth": {
                        "authorization_endpoint": "x",
                        "token_endpoint": "y",
                        "client_id": "c",
                    },
                },
            }
        },
    )
    rc = cli.main(["list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "local-fs" in out and "stdio" in out
    assert "linear" in out and "sse" in out
    assert "oauth" in out  # flag shown


def test_list_json_output(
    monkey_cwd: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write_mcp_json(
        monkey_cwd,
        {
            "mcpServers": {
                "s1": {"command": "x"},
                "s2": {"transport": "sse", "url": "https://x", "disabled": True},
            }
        },
    )
    cli.main(["list", "--json"])
    payload = json.loads(capsys.readouterr().out)
    by_name = {e["name"]: e for e in payload}
    assert by_name["s1"]["transport"] == "stdio"
    assert by_name["s2"]["transport"] == "sse"
    assert by_name["s2"]["disabled"] is True
    assert by_name["s2"]["url"] == "https://x"


# ---- auth ---------------------------------------------------------


def test_auth_server_not_found(
    monkey_cwd: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write_mcp_json(monkey_cwd, {"mcpServers": {}})
    rc = cli.main(["auth", "missing"])
    assert rc == 2
    assert "no server named" in capsys.readouterr().err


def test_auth_server_without_oauth_block(
    monkey_cwd: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write_mcp_json(
        monkey_cwd,
        {
            "mcpServers": {
                "local": {"command": "x"},
            }
        },
    )
    rc = cli.main(["auth", "local"])
    assert rc == 2
    assert "no [oauth] config" in capsys.readouterr().err


def test_auth_runs_flow_and_saves_token(
    monkey_cwd: Path,
    capsys: pytest.CaptureFixture,
    isolated_tokens: Path,
) -> None:
    _write_mcp_json(
        monkey_cwd,
        {
            "mcpServers": {
                "linear": {
                    "transport": "sse",
                    "url": "https://x",
                    "oauth": {
                        "authorization_endpoint": "https://x/auth",
                        "token_endpoint": "https://x/token",
                        "client_id": "c",
                        "scopes": ["read"],
                    },
                }
            }
        },
    )
    fake_token = oauth.StoredToken(
        access_token="AT-NEW",
        refresh_token="RT",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    with patch(
        "athena.mcp.oauth.run_authorization_flow",
        return_value=fake_token,
    ) as run_flow:
        rc = cli.main(["auth", "linear"])
    assert rc == 0
    run_flow.assert_called_once()
    # Token persisted.
    assert oauth.load_token("linear") is not None
    assert "saved token for linear" in capsys.readouterr().out


def test_auth_failure_returns_1(
    monkey_cwd: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write_mcp_json(
        monkey_cwd,
        {
            "mcpServers": {
                "x": {
                    "transport": "sse",
                    "url": "https://x",
                    "oauth": {
                        "authorization_endpoint": "a",
                        "token_endpoint": "t",
                        "client_id": "c",
                    },
                }
            }
        },
    )
    with patch(
        "athena.mcp.oauth.run_authorization_flow",
        side_effect=oauth.OAuthError("user denied"),
    ):
        rc = cli.main(["auth", "x"])
    assert rc == 1
    assert "user denied" in capsys.readouterr().err


def test_auth_no_browser_flag_passes_through(monkey_cwd: Path) -> None:
    _write_mcp_json(
        monkey_cwd,
        {
            "mcpServers": {
                "x": {
                    "transport": "sse",
                    "url": "https://x",
                    "oauth": {
                        "authorization_endpoint": "a",
                        "token_endpoint": "t",
                        "client_id": "c",
                    },
                }
            }
        },
    )
    token = oauth.StoredToken(
        access_token="AT",
        refresh_token=None,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    with patch(
        "athena.mcp.oauth.run_authorization_flow",
        return_value=token,
    ) as run_flow:
        cli.main(["auth", "x", "--no-browser"])
    assert run_flow.call_args.kwargs["open_browser"] is False


# ---- token-status -------------------------------------------------


def test_token_status_empty(
    monkey_cwd: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["token-status"])
    assert rc == 0
    assert "(no tokens stored)" in capsys.readouterr().out


def test_token_status_lists_each_server(
    capsys: pytest.CaptureFixture,
) -> None:
    oauth.save_token(
        "linear",
        oauth.StoredToken(
            access_token="x",
            refresh_token="r",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            scope="read",
        ),
    )
    oauth.save_token(
        "sentry",
        oauth.StoredToken(
            access_token="y",
            refresh_token=None,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            scope="",
        ),
    )
    rc = cli.main(["token-status"])
    out = capsys.readouterr().out
    assert "linear" in out
    assert "sentry" in out
    assert "expired" in out  # the sentry one


def test_token_status_json(capsys: pytest.CaptureFixture) -> None:
    oauth.save_token(
        "x",
        oauth.StoredToken(
            access_token="a",
            refresh_token="r",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ),
    )
    cli.main(["token-status", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert "x" in payload


# ---- revoke -------------------------------------------------------


def test_revoke_removes_token(
    capsys: pytest.CaptureFixture,
) -> None:
    oauth.save_token(
        "zap",
        oauth.StoredToken(
            access_token="a",
            refresh_token=None,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ),
    )
    rc = cli.main(["revoke", "zap"])
    assert rc == 0
    assert oauth.load_token("zap") is None
    assert "deleted" in capsys.readouterr().out


def test_revoke_missing_token_reports_clean(
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["revoke", "never-was"])
    assert rc == 0
    assert "no stored token" in capsys.readouterr().out


# ---- test ---------------------------------------------------------


def test_test_subcommand_unknown_server(
    monkey_cwd: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write_mcp_json(monkey_cwd, {"mcpServers": {}})
    rc = cli.main(["test", "ghost"])
    assert rc == 2


def test_test_subcommand_initializes_and_prints_tools(
    monkey_cwd: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write_mcp_json(
        monkey_cwd,
        {
            "mcpServers": {
                "local": {"command": "fake", "args": []},
            }
        },
    )
    fake = MagicMock()
    fake.initialize.return_value = {}
    fake.list_tools.return_value = [
        {"name": "alpha", "description": "the first one"},
        {"name": "beta", "description": "the second one"},
    ]
    with patch(
        "athena.cli.mcp.open_transport",
        return_value=fake,
    ):
        rc = cli.main(["test", "local"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "alpha" in out and "beta" in out


def test_test_subcommand_initialize_failure_returns_1(
    monkey_cwd: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write_mcp_json(monkey_cwd, {"mcpServers": {"x": {"command": "fake"}}})
    fake = MagicMock()
    fake.initialize.side_effect = RuntimeError("server down")
    with patch(
        "athena.cli.mcp.open_transport",
        return_value=fake,
    ):
        rc = cli.main(["test", "x"])
    assert rc == 1
    assert "server down" in capsys.readouterr().err


def test_test_subcommand_json_output(
    monkey_cwd: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write_mcp_json(monkey_cwd, {"mcpServers": {"x": {"command": "fake"}}})
    fake = MagicMock()
    fake.initialize.return_value = {}
    fake.list_tools.return_value = [{"name": "t1"}]
    with patch(
        "athena.cli.mcp.open_transport",
        return_value=fake,
    ):
        cli.main(["test", "x", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload == [{"name": "t1"}]
