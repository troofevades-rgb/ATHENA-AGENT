"""Translate Hermes' config.yaml into athena v2's config.toml.

Keys we recognize and remap:

  hermes key                   → athena v2 key
  -------------                  --------------
  model                          model
  model_id                       model            (alias)
  ollama_host                    ollama_host
  ollama_endpoint                ollama_host      (alias)
  context_window                 context_window
  max_file_read_bytes            max_file_read
  max_bash_output_bytes          max_bash_output
  auto_approve_tools             auto_approve_tools
  auto_approve_bash              auto_approve_tools  (legacy alias)
  lean_prompt                    lean_prompt
  disabled_tools                 disabled_tools
  bash_allowlist                 bash_allowlist
  max_turn_steps                 max_turn_steps

Anything else is preserved under a top-level ``[hermes]`` table — so we
don't lose the user's customizations, but we don't pretend athena understands
them either.

API-key-shaped values (``*_api_key``, ``*_token``, ``*_secret``) are moved
out of the config and into ``<dest>/credentials.json`` so secrets don't
appear in shareable config diffs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from ..safety.secure_files import ensure_secure_dir, secure_write_json
from .report import Report

_KEY_MAP = {
    "model": "model",
    "model_id": "model",
    "ollama_host": "ollama_host",
    "ollama_endpoint": "ollama_host",
    "context_window": "context_window",
    "max_file_read_bytes": "max_file_read",
    "max_bash_output_bytes": "max_bash_output",
    "auto_approve_tools": "auto_approve_tools",
    "auto_approve_bash": "auto_approve_tools",
    "lean_prompt": "lean_prompt",
    "disabled_tools": "disabled_tools",
    "enabled_toolsets": "enabled_toolsets",
    "bash_allowlist": "bash_allowlist",
    "max_turn_steps": "max_turn_steps",
}

_SECRET_KEY_RE = re.compile(r"(api_key|token|secret|password)", re.IGNORECASE)


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _emit_toml(data: dict[str, Any]) -> str:
    """Hand-rolled TOML emitter — enough for the scalar/array/table shapes
    athena config uses. Avoids adding a third-party TOML *writer* dep to
    a project that only reads TOML at runtime."""
    flat: list[tuple[str, Any]] = []
    nested: list[tuple[str, dict[str, Any]]] = []
    for k, v in data.items():
        if isinstance(v, dict):
            nested.append((k, v))
        else:
            flat.append((k, v))

    parts: list[str] = []
    for k, v in flat:
        parts.append(f"{k} = {_format_value(v)}")
    for table_name, table in nested:
        parts.append("")
        parts.append(f"[{table_name}]")
        for k, v in table.items():
            parts.append(f"{k} = {_format_value(v)}")
    return "\n".join(parts) + "\n"


def _format_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_format_value(item) for item in v) + "]"
    if isinstance(v, dict):
        # Inline table — used only for nested metadata we want to keep
        # together. TOML allows {} for short single-line tables.
        return "{" + ", ".join(f"{k} = {_format_value(val)}" for k, val in v.items()) + "}"
    return f'"{_toml_escape(str(v))}"'


def translate_config(
    source: Path,
    dest: Path,
    *,
    report: Report,
    dry_run: bool = False,
) -> None:
    cfg_path = source / "config.yaml"
    if not cfg_path.exists():
        report.add(
            "config_warning",
            {
                "reason": "no_config_yaml",
                "path": str(cfg_path),
            },
        )
        return

    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        report.add("config_error", {"path": str(cfg_path), "error": str(e)})
        return
    if not isinstance(data, dict):
        report.add("config_error", {"path": str(cfg_path), "error": "top-level is not a mapping"})
        return

    known: dict[str, Any] = {}
    hermes_extras: dict[str, Any] = {}
    credentials: dict[str, Any] = {}

    for key, value in data.items():
        if _SECRET_KEY_RE.search(key):
            credentials[key] = value
            continue
        mapped = _KEY_MAP.get(key)
        if mapped is not None:
            known[mapped] = value
        else:
            hermes_extras[key] = value

    payload: dict[str, Any] = dict(known)
    if hermes_extras:
        payload["hermes"] = hermes_extras

    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "config.toml").write_text(_emit_toml(payload), encoding="utf-8")
        if credentials:
            ensure_secure_dir(dest)
            secure_write_json(dest / "credentials.json", credentials)

    report.add(
        "imported_config",
        {
            "known_keys": sorted(known.keys()),
            "passthrough_keys": sorted(hermes_extras.keys()),
            "credential_keys": sorted(credentials.keys()),
            "dry_run": dry_run,
        },
    )
