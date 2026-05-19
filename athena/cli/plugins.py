"""``athena plugins {list,enable,disable,info}`` — manage plugins.

Enable state is stored in ``~/.athena/plugins_state.json`` (machine-managed).
``config.toml`` stays hand-edited. Per-plugin config slices still go in
``config.toml`` under ``[plugins.<name>]``.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from ..config import load_config, load_plugin_state, save_plugin_state
from ..plugins.discovery import discover
from ..plugins.manifest import PluginManifest


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena plugins")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="Show every discovered plugin and its enabled state.")
    p_enable = sub.add_parser("enable", help="Enable a plugin for future sessions.")
    p_enable.add_argument("name")
    p_disable = sub.add_parser("disable", help="Disable a plugin for future sessions.")
    p_disable.add_argument("name")
    p_info = sub.add_parser("info", help="Show a plugin's manifest and load path.")
    p_info.add_argument("name")
    return ap


def _is_enabled(manifest: PluginManifest, overrides: dict[str, Any]) -> bool:
    if manifest.name in overrides:
        return bool(overrides[manifest.name])
    return manifest.enabled_by_default


def _format_path(manifest: PluginManifest) -> str:
    return str(manifest.path) if manifest.path else "(no path)"


def _list_cmd() -> int:
    manifests = discover()
    if not manifests:
        print("(no plugins discovered)")
        return 0
    cfg = load_config()
    overrides = cfg.plugins.get("enabled") or {}
    rows: list[tuple[str, str, str, str]] = []
    for m in manifests:
        rows.append(
            (
                m.name,
                m.version,
                "enabled" if _is_enabled(m, overrides) else "disabled",
                _format_path(m),
            )
        )
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    for name, version, state, path in rows:
        print(
            f"  {name.ljust(widths[0])}  {version.ljust(widths[1])}  "
            f"{state.ljust(widths[2])}  {path}"
        )
    return 0


def _set_enabled(name: str, enabled: bool) -> int:
    manifests = discover()
    known = {m.name: m for m in manifests}
    if name not in known:
        available = ", ".join(sorted(known)) or "(none)"
        print(
            f"error: unknown plugin {name!r}. Available: {available}",
            file=sys.stderr,
        )
        return 2
    state = load_plugin_state()
    enabled_map = state.get("enabled") if isinstance(state.get("enabled"), dict) else {}
    enabled_map = dict(enabled_map)
    enabled_map[name] = enabled
    state["enabled"] = enabled_map
    save_plugin_state(state)
    verb = "enabled" if enabled else "disabled"
    print(f"{verb} plugin {name!r}. Takes effect on next session.")
    return 0


def _info_cmd(name: str) -> int:
    manifests = discover()
    target = next((m for m in manifests if m.name == name), None)
    if target is None:
        available = ", ".join(sorted(m.name for m in manifests)) or "(none)"
        print(
            f"error: unknown plugin {name!r}. Available: {available}",
            file=sys.stderr,
        )
        return 2
    cfg = load_config()
    overrides = cfg.plugins.get("enabled") or {}
    state = "enabled" if _is_enabled(target, overrides) else "disabled"
    print(f"name:        {target.name}")
    print(f"version:     {target.version}")
    print(f"description: {target.description}")
    print(f"state:       {state}")
    if target.name in overrides:
        print("             (override from plugins_state.json)")
    print(f"path:        {_format_path(target)}")
    if target.depends_on:
        print(f"depends_on:  {', '.join(target.depends_on)}")
    if target.config_schema:
        print(f"config_schema: {target.config_schema}")
    return 0


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "list":
        return _list_cmd()
    if args.cmd == "enable":
        return _set_enabled(args.name, True)
    if args.cmd == "disable":
        return _set_enabled(args.name, False)
    if args.cmd == "info":
        return _info_cmd(args.name)
    return 2
