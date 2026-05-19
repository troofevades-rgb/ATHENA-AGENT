"""Tests for athena.migration.config_translator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from athena.migration.config_translator import translate_config


def _write_hermes_config(src: Path, data: dict) -> Path:
    p = src / "config.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def _read_toml(p: Path) -> dict:
    return tomllib.loads(p.read_text(encoding="utf-8"))


def test_translates_known_keys(hermes_source: Path, ocode_dest: Path, migration_report) -> None:
    _write_hermes_config(
        hermes_source,
        {
            "model": "qwen2.5-coder:14b",
            "ollama_host": "http://localhost:11434",
            "context_window": 32768,
            "max_turn_steps": 25,
            "auto_approve_tools": True,
        },
    )
    translate_config(hermes_source, ocode_dest, report=migration_report)

    data = _read_toml(ocode_dest / "config.toml")
    assert data["model"] == "qwen2.5-coder:14b"
    assert data["ollama_host"] == "http://localhost:11434"
    assert data["context_window"] == 32768
    assert data["max_turn_steps"] == 25
    assert data["auto_approve_tools"] is True


def test_unknown_keys_passed_to_hermes_section(
    hermes_source: Path, ocode_dest: Path, migration_report
) -> None:
    _write_hermes_config(
        hermes_source,
        {
            "model": "x",
            "hermes_specific_thing": "value",
            "another_quirk": 42,
        },
    )
    translate_config(hermes_source, ocode_dest, report=migration_report)

    data = _read_toml(ocode_dest / "config.toml")
    assert data["model"] == "x"
    assert data["hermes"]["hermes_specific_thing"] == "value"
    assert data["hermes"]["another_quirk"] == 42


def test_yaml_to_toml_round_trip_preserves_structure(
    hermes_source: Path, ocode_dest: Path, migration_report
) -> None:
    _write_hermes_config(
        hermes_source,
        {
            "model": "m1",
            "bash_allowlist": ["git status", "ls"],
            "disabled_tools": ["Write"],
            "lean_prompt": False,
        },
    )
    translate_config(hermes_source, ocode_dest, report=migration_report)
    data = _read_toml(ocode_dest / "config.toml")
    assert data["bash_allowlist"] == ["git status", "ls"]
    assert data["disabled_tools"] == ["Write"]
    assert data["lean_prompt"] is False


def test_api_keys_moved_to_credentials_json(
    hermes_source: Path, ocode_dest: Path, migration_report
) -> None:
    _write_hermes_config(
        hermes_source,
        {
            "model": "m1",
            "openai_api_key": "sk-fake",
            "github_token": "ghp-fake",
            "session_secret": "shh",
        },
    )
    translate_config(hermes_source, ocode_dest, report=migration_report)

    config = _read_toml(ocode_dest / "config.toml")
    assert "openai_api_key" not in config
    assert "github_token" not in config
    assert "session_secret" not in config

    creds = json.loads((ocode_dest / "credentials.json").read_text(encoding="utf-8"))
    assert creds == {
        "openai_api_key": "sk-fake",
        "github_token": "ghp-fake",
        "session_secret": "shh",
    }


def test_legacy_aliases(hermes_source: Path, ocode_dest: Path, migration_report) -> None:
    _write_hermes_config(
        hermes_source,
        {
            "ollama_endpoint": "http://x:1",
            "auto_approve_bash": True,
            "max_file_read_bytes": 999,
        },
    )
    translate_config(hermes_source, ocode_dest, report=migration_report)
    data = _read_toml(ocode_dest / "config.toml")
    assert data["ollama_host"] == "http://x:1"
    assert data["auto_approve_tools"] is True
    assert data["max_file_read"] == 999


def test_warns_when_no_config(hermes_source: Path, ocode_dest: Path, migration_report) -> None:
    translate_config(hermes_source, ocode_dest, report=migration_report)
    warnings = migration_report.entries.get("config_warning", [])
    assert any(w.get("reason") == "no_config_yaml" for w in warnings)
