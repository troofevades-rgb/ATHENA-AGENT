"""Tests for ocode.migration.mcp_translator."""
from __future__ import annotations

import json
from pathlib import Path

from ocode.migration.mcp_translator import translate_mcp


def _write_mcp(src: Path, data: dict) -> Path:
    p = src / "mcp.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def test_copies_mcp_json_verbatim(
    hermes_source: Path, ocode_dest: Path, migration_report
) -> None:
    data = {
        "mcpServers": {
            "fs": {"command": "uvx", "args": ["mcp-fs"]},
            "github": {"command": "uvx", "args": ["mcp-github"]},
        }
    }
    _write_mcp(hermes_source, data)
    translate_mcp(hermes_source, ocode_dest, report=migration_report)

    out = json.loads((ocode_dest / "mcp.json").read_text(encoding="utf-8"))
    assert out["mcpServers"]["fs"]["command"] == "uvx"
    assert out["mcpServers"]["github"]["args"] == ["mcp-github"]


def test_disables_http_sse_servers_when_phase_12_unavailable(
    hermes_source: Path, ocode_dest: Path, migration_report
) -> None:
    _write_mcp(hermes_source, {
        "mcpServers": {
            "stdio-one": {"command": "x"},
            "http-one": {"transport": "http", "url": "http://x"},
            "sse-one": {"transport": "sse", "url": "http://y"},
        }
    })
    translate_mcp(hermes_source, ocode_dest, report=migration_report)
    out = json.loads((ocode_dest / "mcp.json").read_text(encoding="utf-8"))
    assert out["mcpServers"]["stdio-one"].get("disabled") is not True
    assert out["mcpServers"]["http-one"]["disabled"] is True
    assert out["mcpServers"]["sse-one"]["disabled"] is True
    warnings = migration_report.entries.get("mcp_warning", [])
    transports = sorted(w.get("transport") for w in warnings if "transport" in w)
    assert transports == ["http", "sse"]


def test_warns_when_no_mcp_json(
    hermes_source: Path, ocode_dest: Path, migration_report
) -> None:
    translate_mcp(hermes_source, ocode_dest, report=migration_report)
    warnings = migration_report.entries.get("mcp_warning", [])
    assert any(w.get("reason") == "no_mcp_json" for w in warnings)


def test_records_error_on_malformed_json(
    hermes_source: Path, ocode_dest: Path, migration_report
) -> None:
    (hermes_source / "mcp.json").write_text("{ not json", encoding="utf-8")
    translate_mcp(hermes_source, ocode_dest, report=migration_report)
    assert migration_report.count("mcp_error") == 1
    assert not (ocode_dest / "mcp.json").exists()


def test_records_error_when_servers_not_mapping(
    hermes_source: Path, ocode_dest: Path, migration_report
) -> None:
    _write_mcp(hermes_source, {"mcpServers": ["not", "a", "dict"]})
    translate_mcp(hermes_source, ocode_dest, report=migration_report)
    errors = migration_report.entries.get("mcp_error", [])
    assert any("not a mapping" in e.get("error", "") for e in errors)


def test_non_dict_server_entry_skipped(
    hermes_source: Path, ocode_dest: Path, migration_report
) -> None:
    _write_mcp(hermes_source, {"mcpServers": {
        "ok": {"command": "x"},
        "weird": "not a dict",
    }})
    translate_mcp(hermes_source, ocode_dest, report=migration_report)
    out = json.loads((ocode_dest / "mcp.json").read_text(encoding="utf-8"))
    assert out["mcpServers"]["ok"]["command"] == "x"
    assert out["mcpServers"]["weird"] == "not a dict"
