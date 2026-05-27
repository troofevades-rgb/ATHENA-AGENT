"""Tests for ``/mcp`` — list connected MCP servers, tail stderr."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from athena.commands.mcp_cmd import cmd_mcp


def _capture():
    lines: list[str] = []
    patches = []
    for fn in ("info", "warn", "error"):
        patches.append(
            patch(
                f"athena.commands.mcp_cmd.ui.{fn}",
                side_effect=lambda msg, *a, _n=fn, **kw:
                    lines.append(f"{_n}: {msg}"),
            )
        )
    patches.append(
        patch(
            "athena.commands.mcp_cmd.ui.console.print",
            side_effect=lambda *a, **kw:
                lines.append(" ".join(str(x) for x in a)),
        )
    )
    return lines, patches


def _run(arg: str, clients: list) -> str:
    lines, patches = _capture()
    for p in patches:
        p.start()
    try:
        with patch("athena.commands.mcp_cmd.active_clients", return_value=clients):
            cmd_mcp(SimpleNamespace(), arg)
    finally:
        for p in patches:
            p.stop()
    return "\n".join(lines)


def _fake_client(
    name: str,
    *,
    alive: bool = True,
    version: str = "1.0.0",
    tools: list | None = None,
    stderr: list[str] | None = None,
):
    """Build a fake MCP client matching the surface cmd_mcp uses."""
    return SimpleNamespace(
        name=name,
        is_alive=lambda: alive,
        _tools=tools or [],
        _server_info={"serverInfo": {"version": version}},
        stderr_tail=lambda n: (stderr or [])[-n:],
    )


# ---- /mcp (no args) — list servers ----------------------------------


def test_no_servers_shows_help_message() -> None:
    out = _run("", [])
    assert "no MCP servers" in out.lower() or "no mcp servers" in out.lower()
    # Tells the user where to configure
    assert "mcp.json" in out


def test_lists_alive_server_with_version_and_tool_count() -> None:
    clients = [_fake_client(
        "github", alive=True, version="2.1.0",
        tools=[{"name": "create_issue"}, {"name": "list_repos"}],
    )]
    out = _run("", clients)
    assert "github" in out
    assert "alive" in out
    assert "2.1.0" in out
    assert "2 tools" in out


def test_lists_dead_server_as_dead() -> None:
    clients = [_fake_client("broken", alive=False)]
    out = _run("", clients)
    assert "broken" in out
    assert "dead" in out


def test_lists_multiple_servers() -> None:
    clients = [
        _fake_client("alpha", tools=[{"n": 1}]),
        _fake_client("beta", tools=[{"n": 2}, {"n": 3}, {"n": 4}]),
        _fake_client("gamma", alive=False),
    ]
    out = _run("", clients)
    assert "alpha" in out
    assert "beta" in out
    assert "3 tools" in out
    assert "gamma" in out
    assert "dead" in out


def test_handles_missing_server_info_gracefully() -> None:
    """When _server_info is None (some transports don't expose it),
    version should fall back to '?' rather than KeyError."""
    client = SimpleNamespace(
        name="weird",
        is_alive=lambda: True,
        _tools=[],
        _server_info=None,
        stderr_tail=lambda n: [],
    )
    out = _run("", [client])
    assert "weird" in out
    assert "v?" in out


# ---- /mcp logs NAME -------------------------------------------------


def test_logs_without_name_errors() -> None:
    out = _run("logs", [_fake_client("x")])
    assert "usage" in out.lower()
    assert "logs" in out.lower()


def test_logs_for_unknown_server_errors() -> None:
    out = _run("logs ghost", [_fake_client("real")])
    assert "no server" in out.lower()
    assert "ghost" in out


def test_logs_tails_stderr() -> None:
    client = _fake_client(
        "noisy",
        stderr=[
            "line 1",
            "line 2",
            "WARN: something happened",
            "line 4",
        ],
    )
    out = _run("logs noisy", [client])
    for expected in ("line 1", "line 2", "WARN", "line 4"):
        assert expected in out


def test_logs_empty_stderr_shows_friendly_message() -> None:
    client = _fake_client("quiet", stderr=[])
    out = _run("logs quiet", [client])
    assert "no stderr" in out.lower()
    assert "quiet" in out


# ---- /mcp <unknown subcommand> --------------------------------------


def test_unknown_subcommand_errors() -> None:
    out = _run("frobnicate", [_fake_client("x")])
    assert "unknown" in out.lower()
    assert "frobnicate" in out
