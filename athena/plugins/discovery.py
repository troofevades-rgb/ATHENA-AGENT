"""Plugin discovery — walk bundled and user plugin directories.

A plugin is a directory containing both ``plugin.toml`` and ``plugin.py``.
Anything missing either file is skipped with a logged ``info`` message and
not surfaced as an error — discovery is best-effort.

Two roots are scanned, in order:

1. ``athena/plugins/bundled/`` — ships with the package; not user-editable.
2. ``~/.athena/plugins/`` — user-installed plugins.

A plugin's directory name doesn't have to match the manifest ``name``; the
loader keys off the manifest.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .manifest import ManifestError, PluginManifest, parse_manifest

logger = logging.getLogger(__name__)


BUNDLED_DIR = Path(__file__).parent / "bundled"
USER_DIR = Path.home() / ".athena" / "plugins"


def _scan_root(root: Path) -> list[PluginManifest]:
    """Return manifests for every well-formed plugin under ``root``.

    Skips entries that aren't directories, lack ``plugin.toml`` or
    ``plugin.py``, or whose manifest fails to parse — each with a logged
    ``info`` so the user can diagnose silent misses.
    """
    if not root.exists():
        return []
    out: list[PluginManifest] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        # Skip dunder directories like __pycache__.
        if entry.name.startswith("_"):
            continue
        manifest_path = entry / "plugin.toml"
        module_path = entry / "plugin.py"
        if not manifest_path.exists():
            logger.info("plugin %s: skipped (no plugin.toml)", entry.name)
            continue
        if not module_path.exists():
            logger.info("plugin %s: skipped (no plugin.py)", entry.name)
            continue
        try:
            out.append(parse_manifest(manifest_path))
        except ManifestError as e:
            logger.info("plugin %s: skipped (%s)", entry.name, e)
    return out


def discover(
    *,
    bundled_dir: Path | None = None,
    user_dir: Path | None = None,
) -> list[PluginManifest]:
    """Return manifests for every plugin found under bundled + user dirs.

    Arguments default to the package's bundled directory and ``~/.athena/
    plugins/``. They're override-able for tests, which point at temp dirs.
    """
    bundled_dir = bundled_dir if bundled_dir is not None else BUNDLED_DIR
    user_dir = user_dir if user_dir is not None else USER_DIR
    return [*_scan_root(bundled_dir), *_scan_root(user_dir)]
