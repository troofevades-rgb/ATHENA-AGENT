"""resolve_js_runtime: node -> bun fallback so a Bun-only machine launches
the TUI without ATHENA_NODE_BIN (the cross-machine pain point)."""

from __future__ import annotations

import athena.tui_gateway.server as server
from athena.tui_gateway.server import resolve_js_runtime


def _which(table: dict[str, str]):
    return lambda name: table.get(name)


def test_explicit_arg_wins(monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_NODE_BIN", "envbun")
    monkeypatch.setattr(server.shutil, "which", _which({"node": "/usr/bin/node"}))
    assert resolve_js_runtime("/custom/runtime") == "/custom/runtime"


def test_env_var_over_path(monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_NODE_BIN", "envbun")
    monkeypatch.setattr(server.shutil, "which", _which({"node": "/usr/bin/node"}))
    assert resolve_js_runtime() == "envbun"


def test_node_preferred_when_both_present(monkeypatch) -> None:
    monkeypatch.delenv("ATHENA_NODE_BIN", raising=False)
    monkeypatch.setattr(
        server.shutil, "which", _which({"node": "/usr/bin/node", "bun": "/usr/bin/bun"})
    )
    assert resolve_js_runtime() == "/usr/bin/node"


def test_bun_fallback_when_node_missing(monkeypatch) -> None:
    monkeypatch.delenv("ATHENA_NODE_BIN", raising=False)
    monkeypatch.setattr(server.shutil, "which", _which({"bun": "/home/u/.bun/bin/bun"}))
    assert resolve_js_runtime() == "/home/u/.bun/bin/bun"


def test_defaults_to_node_when_neither_found(monkeypatch) -> None:
    # So a missing-runtime spawn still raises a clear FileNotFoundError.
    monkeypatch.delenv("ATHENA_NODE_BIN", raising=False)
    monkeypatch.setattr(server.shutil, "which", _which({}))
    assert resolve_js_runtime() == "node"
