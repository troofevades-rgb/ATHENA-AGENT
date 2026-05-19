"""Transport resolver — picks stdio vs SSE based on mcp.json entry."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from athena.mcp import transport_resolver
from athena.mcp.oauth import OAuthConfig

# ---- stdio path -----------------------------------------------------


def test_stdio_default_when_no_transport_field() -> None:
    """Existing mcp.json entries without a transport key still work."""
    with patch("athena.mcp.client.MCPStdioClient") as cls:
        cls.return_value = MagicMock()
        transport_resolver.open_transport("srv", {"command": "node", "args": ["x"]})
    cls.assert_called_once()
    kwargs = cls.call_args.kwargs
    assert kwargs["command"] == "node"
    assert kwargs["args"] == ["x"]
    assert kwargs["name"] == "srv"


def test_stdio_when_explicitly_set() -> None:
    with patch("athena.mcp.client.MCPStdioClient") as cls:
        cls.return_value = MagicMock()
        transport_resolver.open_transport(
            "srv",
            {"transport": "stdio", "command": "python", "args": ["m"]},
        )
    cls.assert_called_once()


def test_stdio_passes_env_and_cwd() -> None:
    with patch("athena.mcp.client.MCPStdioClient") as cls:
        cls.return_value = MagicMock()
        transport_resolver.open_transport(
            "srv",
            {
                "command": "node",
                "env": {"K": "V"},
                "cwd": "/some/path",
            },
        )
    kwargs = cls.call_args.kwargs
    assert kwargs["env"] == {"K": "V"}
    assert kwargs["cwd"] == "/some/path"


def test_stdio_missing_command_raises() -> None:
    with pytest.raises(ValueError, match="requires 'command'"):
        transport_resolver.open_transport("srv", {})


def test_stdio_missing_command_with_explicit_transport_raises() -> None:
    with pytest.raises(ValueError, match="requires 'command'"):
        transport_resolver.open_transport(
            "srv",
            {"transport": "stdio"},
        )


# ---- sse / http path ------------------------------------------------


def test_sse_transport_constructed_when_specified() -> None:
    with patch("athena.mcp.sse_transport.SSETransport") as cls:
        cls.return_value = MagicMock()
        transport_resolver.open_transport(
            "linear",
            {"transport": "sse", "url": "https://mcp.linear.app/sse"},
        )
    cls.assert_called_once()
    kwargs = cls.call_args.kwargs
    assert kwargs["base_url"] == "https://mcp.linear.app/sse"
    assert kwargs["oauth_cfg"] is None


def test_http_alias_routes_to_sse_transport() -> None:
    """``http`` and ``sse`` both produce the same transport."""
    with patch("athena.mcp.sse_transport.SSETransport") as cls:
        cls.return_value = MagicMock()
        transport_resolver.open_transport(
            "x",
            {"transport": "http", "url": "https://x"},
        )
    cls.assert_called_once()


def test_http_plus_sse_alias_works() -> None:
    with patch("athena.mcp.sse_transport.SSETransport") as cls:
        cls.return_value = MagicMock()
        transport_resolver.open_transport(
            "x",
            {"transport": "http+sse", "url": "https://x"},
        )
    cls.assert_called_once()


def test_sse_case_insensitive() -> None:
    with patch("athena.mcp.sse_transport.SSETransport") as cls:
        cls.return_value = MagicMock()
        transport_resolver.open_transport(
            "x",
            {"transport": "SSE", "url": "https://x"},
        )
    cls.assert_called_once()


def test_sse_missing_url_raises() -> None:
    with pytest.raises(ValueError, match="requires 'url'"):
        transport_resolver.open_transport(
            "srv",
            {"transport": "sse"},
        )


def test_sse_with_oauth_config_parsed() -> None:
    with patch("athena.mcp.sse_transport.SSETransport") as cls:
        cls.return_value = MagicMock()
        transport_resolver.open_transport(
            "linear",
            {
                "transport": "sse",
                "url": "https://mcp.linear.app/sse",
                "oauth": {
                    "authorization_endpoint": "https://linear.app/oauth/authorize",
                    "token_endpoint": "https://api.linear.app/oauth/token",
                    "client_id": "abc123",
                    "scopes": ["read", "write"],
                    "audience": "https://api.linear.app",
                },
            },
        )
    oauth_cfg = cls.call_args.kwargs["oauth_cfg"]
    assert isinstance(oauth_cfg, OAuthConfig)
    assert oauth_cfg.server_id == "linear"
    assert oauth_cfg.client_id == "abc123"
    assert oauth_cfg.scopes == ["read", "write"]
    assert oauth_cfg.audience == "https://api.linear.app"


def test_oauth_missing_required_field_raises() -> None:
    with pytest.raises(ValueError, match="client_id"):
        transport_resolver.open_transport(
            "x",
            {
                "transport": "sse",
                "url": "https://x",
                "oauth": {
                    "authorization_endpoint": "https://x/auth",
                    "token_endpoint": "https://x/token",
                    # missing client_id
                },
            },
        )


def test_oauth_must_be_object() -> None:
    with pytest.raises(ValueError, match="must be a table"):
        transport_resolver.open_transport(
            "x",
            {
                "transport": "sse",
                "url": "https://x",
                "oauth": "not a dict",
            },
        )


def test_oauth_scopes_must_be_list() -> None:
    with pytest.raises(ValueError, match="scopes must be a list"):
        transport_resolver.open_transport(
            "x",
            {
                "transport": "sse",
                "url": "https://x",
                "oauth": {
                    "authorization_endpoint": "https://x/a",
                    "token_endpoint": "https://x/t",
                    "client_id": "c",
                    "scopes": "read write",  # should be a list
                },
            },
        )


def test_oauth_no_audience_ok() -> None:
    """Audience is optional — most providers don't need it."""
    with patch("athena.mcp.sse_transport.SSETransport") as cls:
        cls.return_value = MagicMock()
        transport_resolver.open_transport(
            "x",
            {
                "transport": "sse",
                "url": "https://x",
                "oauth": {
                    "authorization_endpoint": "https://x/a",
                    "token_endpoint": "https://x/t",
                    "client_id": "c",
                },
            },
        )
    oauth_cfg = cls.call_args.kwargs["oauth_cfg"]
    assert oauth_cfg.audience is None


# ---- unknown transport --------------------------------------------


def test_unknown_transport_raises() -> None:
    with pytest.raises(ValueError, match="unknown transport"):
        transport_resolver.open_transport(
            "x",
            {"transport": "telepathy"},
        )


# ---- loader integration -----------------------------------------


def test_loader_routes_via_resolver(tmp_path) -> None:
    """An mcp.json with a transport: sse entry should reach
    SSETransport via the resolver."""
    import json

    from athena.mcp import loader

    cfg_path = tmp_path / "mcp.json"
    cfg_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "remote": {
                        "transport": "sse",
                        "url": "https://x.example.com/sse",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with patch("athena.mcp.sse_transport.SSETransport") as cls:
        mock_client = MagicMock()
        mock_client.initialize.return_value = {}
        mock_client.list_tools.return_value = []
        cls.return_value = mock_client
        started = loader.load_mcp_servers([cfg_path])
    assert len(started) == 1
    cls.assert_called_once()


def test_loader_stdio_path_unchanged(tmp_path) -> None:
    """Stdio entries continue to construct MCPStdioClient."""
    import json

    from athena.mcp import loader

    cfg_path = tmp_path / "mcp.json"
    cfg_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local": {
                        "command": "fake-cmd",
                        "args": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with patch("athena.mcp.client.MCPStdioClient") as cls:
        mock_client = MagicMock()
        mock_client.initialize.return_value = {}
        mock_client.list_tools.return_value = []
        cls.return_value = mock_client
        loader.load_mcp_servers([cfg_path])
    cls.assert_called_once()


def test_loader_skips_disabled_regardless_of_transport(tmp_path) -> None:
    import json

    from athena.mcp import loader

    cfg_path = tmp_path / "mcp.json"
    cfg_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "off": {
                        "transport": "sse",
                        "url": "https://x",
                        "disabled": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with patch("athena.mcp.sse_transport.SSETransport") as cls:
        loader.load_mcp_servers([cfg_path])
    cls.assert_not_called()


def test_loader_reports_unknown_transport_via_log(tmp_path) -> None:
    import json

    from athena.mcp import loader

    cfg_path = tmp_path / "mcp.json"
    cfg_path.write_text(
        json.dumps({"mcpServers": {"weird": {"transport": "telepathy", "url": "x"}}}),
        encoding="utf-8",
    )

    messages: list[tuple[str, str]] = []
    started = loader.load_mcp_servers(
        [cfg_path],
        on_message=lambda lvl, msg: messages.append((lvl, msg)),
    )
    assert started == []
    assert any(lvl == "error" and "unknown transport" in msg for lvl, msg in messages)
