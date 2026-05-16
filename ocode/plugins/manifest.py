"""Plugin manifest (``plugin.toml``) parsing.

Every plugin lives in its own directory and declares itself via a
``plugin.toml`` at the directory root. The manifest is parsed once at
discovery time; everything downstream (load order, enabled state, dependency
resolution) reads from the parsed :class:`PluginManifest`.

Example::

    [plugin]
    name = "shell_audit"
    version = "0.1.0"
    description = "Append every shell tool call to a per-session audit log."
    enabled_by_default = false
    depends_on = ["other_plugin"]
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore


class ManifestError(ValueError):
    """Raised when ``plugin.toml`` is missing required fields or malformed."""


@dataclass
class PluginManifest:
    """Parsed contents of a single plugin's ``plugin.toml``.

    ``path`` is the directory the manifest was read from — i.e. the plugin
    root. The loader joins it with ``plugin.py`` to locate the module.
    """
    name: str
    version: str
    description: str = ""
    enabled_by_default: bool = True
    depends_on: list[str] = field(default_factory=list)
    config_schema: dict[str, Any] | None = None
    path: Path | None = None


def parse_manifest(manifest_path: Path) -> PluginManifest:
    """Read a ``plugin.toml`` and return a :class:`PluginManifest`.

    Raises :class:`ManifestError` if the file is missing the ``[plugin]``
    section, missing the required ``name`` or ``version`` keys, or if the
    file is not valid TOML.
    """
    try:
        with open(manifest_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{manifest_path}: invalid TOML — {e}") from e

    plugin_data = data.get("plugin")
    if not isinstance(plugin_data, dict):
        raise ManifestError(
            f"{manifest_path}: missing [plugin] section"
        )

    name = plugin_data.get("name")
    version = plugin_data.get("version")
    if not name:
        raise ManifestError(f"{manifest_path}: [plugin] missing 'name'")
    if not version:
        raise ManifestError(f"{manifest_path}: [plugin] missing 'version'")

    depends_on = plugin_data.get("depends_on", [])
    if not isinstance(depends_on, list) or not all(
        isinstance(d, str) for d in depends_on
    ):
        raise ManifestError(
            f"{manifest_path}: 'depends_on' must be a list of strings"
        )

    return PluginManifest(
        name=str(name),
        version=str(version),
        description=str(plugin_data.get("description", "")),
        enabled_by_default=bool(plugin_data.get("enabled_by_default", True)),
        depends_on=list(depends_on),
        config_schema=plugin_data.get("config_schema"),
        path=manifest_path.parent,
    )
