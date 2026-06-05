"""Startup hardening for ``load_mcp_servers``.

Regression context: the MCP connect was synchronous with a 30s-per-server
handshake stall and no feedback, so a single non-responsive server
(``red-team-mcp`` / ``hexstrike`` in the field) bricked the entire CLI
launch. These tests pin the contract that fixes it: a per-server startup
timeout (overridable in the entry, defaulting to a configurable global),
fail-soft isolation, and a "connecting…" announcement before the blocking
handshake.

The transport layer is faked via ``open_transport`` so the tests stay
hermetic — no real subprocesses or sockets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from athena.mcp import loader
from athena.mcp.client import MCPError


class _FakeTransport:
    def __init__(self, name: str, *, fail_init: bool = False) -> None:
        self.name = name
        self._fail_init = fail_init
        self.closed = False

    def initialize(self) -> dict[str, Any]:
        if self._fail_init:
            # Mirrors the message MCPStdioClient.request raises on a
            # startup-handshake timeout.
            raise MCPError(f"timeout waiting for 'initialize' from {self.name!r}")
        return {}

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "do_thing", "description": "d", "inputSchema": {"type": "object"}}]

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _clean_registry():
    """Keep the global MCP client list from leaking across tests."""
    yield
    loader.shutdown_all()


def _write_cfg(tmp_path: Path, servers: dict[str, Any]) -> Path:
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    return p


# ---- timeout resolution --------------------------------------------------


def test_coerce_timeout_handles_overrides_and_junk() -> None:
    assert loader._coerce_timeout(3, 10.0) == 3.0
    assert loader._coerce_timeout("5.5", 10.0) == 5.5
    assert loader._coerce_timeout(None, 10.0) == 10.0  # absent → default
    assert loader._coerce_timeout("abc", 10.0) == 10.0  # non-numeric → default
    assert loader._coerce_timeout(0, 10.0) == 10.0  # non-positive → default
    assert loader._coerce_timeout(-4, 10.0) == 10.0


def test_per_server_timeout_override_and_global_default(tmp_path, monkeypatch) -> None:
    captured: dict[str, float | None] = {}

    def fake_open(name, scfg, *, startup_timeout=None):
        captured[name] = startup_timeout
        return _FakeTransport(name)

    monkeypatch.setattr(loader, "open_transport", fake_open)
    monkeypatch.setattr(loader, "_register_mcp_tool", lambda *a, **k: None)

    cfg = _write_cfg(
        tmp_path,
        {
            "fast": {"command": "x"},
            "slow": {"command": "y", "startup_timeout": 3},
        },
    )
    loader.load_mcp_servers([cfg], default_timeout=10.0)

    assert captured["fast"] == 10.0  # inherits the global default
    assert captured["slow"] == 3.0  # per-server override wins


# ---- fail-soft isolation -------------------------------------------------


def test_unresponsive_server_skipped_others_still_load(tmp_path, monkeypatch) -> None:
    made: dict[str, _FakeTransport] = {}

    def fake_open(name, scfg, *, startup_timeout=None):
        t = _FakeTransport(name, fail_init=(name == "hung"))
        made[name] = t
        return t

    monkeypatch.setattr(loader, "open_transport", fake_open)
    monkeypatch.setattr(loader, "_register_mcp_tool", lambda *a, **k: None)

    logs: list[tuple[str, str]] = []
    cfg = _write_cfg(
        tmp_path,
        {
            "hung": {"command": "x"},
            "ok": {"command": "y"},
        },
    )
    started = loader.load_mcp_servers(
        [cfg], on_message=lambda lvl, msg: logs.append((lvl, msg)), default_timeout=2.0
    )

    # The hung server is skipped; the healthy one still loads.
    assert [c.name for c in started] == ["ok"]
    assert made["hung"].closed is True  # cleaned up on failure

    # Feedback: announced before connecting, and a clear skip warning.
    assert any("connecting" in msg for _, msg in logs)
    assert any(
        lvl == "warn" and "hung" in msg and "did not start" in msg for lvl, msg in logs
    )


def test_connecting_message_emitted_per_server(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        loader, "open_transport", lambda name, scfg, *, startup_timeout=None: _FakeTransport(name)
    )
    monkeypatch.setattr(loader, "_register_mcp_tool", lambda *a, **k: None)

    logs: list[tuple[str, str]] = []
    cfg = _write_cfg(tmp_path, {"a": {"command": "x"}, "b": {"command": "y"}})
    loader.load_mcp_servers(
        [cfg], on_message=lambda lvl, msg: logs.append((lvl, msg)), default_timeout=7.0
    )

    connecting = [msg for lvl, msg in logs if "connecting" in msg]
    assert len(connecting) == 2
    assert all("7s" in msg for msg in connecting)  # shows the timeout
