"""Plugin loader — import each plugin module, instantiate its Plugin subclass.

Steps:

1. Filter by enabled state: ``config["plugins"]["enabled"][<name>]`` overrides
   the manifest's ``enabled_by_default``.
2. Topologically sort by ``depends_on``. Cycles raise
   :class:`PluginDependencyError`.
3. For each manifest, ``importlib`` the ``plugin.py`` from its directory.
4. Find the single :class:`Plugin` subclass defined in that module.
5. Instantiate with the plugin's config slice and bind ``name`` / ``version``
   from the manifest.
6. Call ``on_install`` exactly once per plugin (tracked via
   ``~/.ocode/plugins_installed``).
7. Return instances in topological order.

The loader is intentionally silent on missing dependencies (skips them with
an ``info`` log) and noisy on cycles (raises). Missing deps are recoverable
when the user installs them; cycles are a manifest bug that must be fixed.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from .base import Plugin
from .manifest import PluginManifest

logger = logging.getLogger(__name__)


INSTALLED_MARKER = Path.home() / ".ocode" / "plugins_installed"


class PluginDependencyError(RuntimeError):
    """Raised when plugin manifests form a dependency cycle."""


def _toposort(manifests: list[PluginManifest]) -> list[PluginManifest]:
    """Return ``manifests`` ordered so that every plugin's deps appear first.

    Plugins depending on a manifest that wasn't passed in are kept (the loader
    can't enforce dependencies that aren't installed — it logs the miss).
    Cycles raise :class:`PluginDependencyError` with the offending nodes.
    """
    by_name = {m.name: m for m in manifests}
    visited: dict[str, str] = {}  # "visiting" | "done"
    order: list[PluginManifest] = []

    def visit(name: str, stack: list[str]) -> None:
        state = visited.get(name)
        if state == "done":
            return
        if state == "visiting":
            cycle = " -> ".join([*stack, name])
            raise PluginDependencyError(f"plugin dependency cycle: {cycle}")
        if name not in by_name:
            return  # external/missing dep — not our problem to enforce here
        visited[name] = "visiting"
        for dep in by_name[name].depends_on:
            visit(dep, [*stack, name])
        visited[name] = "done"
        order.append(by_name[name])

    for m in manifests:
        visit(m.name, [])
    return order


def _enabled(manifest: PluginManifest, config: dict[str, Any]) -> bool:
    """Resolve enabled state: explicit override beats manifest default."""
    overrides = (config.get("plugins") or {}).get("enabled") or {}
    if manifest.name in overrides:
        return bool(overrides[manifest.name])
    return manifest.enabled_by_default


def _import_plugin_module(manifest: PluginManifest):
    """Import ``plugin.py`` from the manifest's directory.

    Uses a unique module name (``ocode_plugin__<plugin_name>``) so multiple
    plugins don't clobber each other's modules in ``sys.modules``.
    """
    assert manifest.path is not None
    module_path = manifest.path / "plugin.py"
    mod_name = f"ocode_plugin__{manifest.name}"
    spec = importlib.util.spec_from_file_location(mod_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load plugin {manifest.name} from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def _find_plugin_subclass(module) -> type[Plugin]:
    """Return the single :class:`Plugin` subclass declared in ``module``.

    Subclasses defined in the module (not re-imported from elsewhere) and
    that are strict subclasses of :class:`Plugin` (not :class:`Plugin` itself)
    qualify. Raises if zero or multiple candidates are present.
    """
    candidates: list[type[Plugin]] = []
    for attr_name in dir(module):
        obj = getattr(module, attr_name)
        if not isinstance(obj, type):
            continue
        if obj is Plugin:
            continue
        if not issubclass(obj, Plugin):
            continue
        # Only count classes defined in this module — otherwise re-importing
        # Plugin via `from ocode.plugins.base import Plugin` would always count.
        if obj.__module__ != module.__name__:
            continue
        candidates.append(obj)
    if not candidates:
        raise ImportError(
            f"{module.__name__}: no Plugin subclass defined in plugin.py"
        )
    if len(candidates) > 1:
        names = ", ".join(c.__name__ for c in candidates)
        raise ImportError(
            f"{module.__name__}: multiple Plugin subclasses ({names}); "
            "exactly one is required"
        )
    return candidates[0]


def _mark_installed(plugin_name: str, marker_path: Path) -> bool:
    """Record that ``plugin_name`` has been installed. Return True if this
    was the first time (i.e. ``on_install`` should fire)."""
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if marker_path.exists():
        try:
            existing = {
                line.strip() for line in
                marker_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
        except OSError:
            existing = set()
    if plugin_name in existing:
        return False
    existing.add(plugin_name)
    marker_path.write_text("\n".join(sorted(existing)) + "\n", encoding="utf-8")
    return True


def load_plugins(
    manifests: list[PluginManifest],
    config: dict[str, Any],
    *,
    installed_marker: Path | None = None,
) -> list[Plugin]:
    """Load and instantiate every enabled plugin.

    ``config`` is the agent's full config dict; the loader reads
    ``config["plugins"]["enabled"]`` (per-name overrides) and
    ``config["plugins"][<name>]`` (per-plugin config slice).
    """
    marker = installed_marker if installed_marker is not None else INSTALLED_MARKER

    enabled_manifests = [m for m in manifests if _enabled(m, config)]
    ordered = _toposort(enabled_manifests)
    plugins_cfg = config.get("plugins") or {}

    out: list[Plugin] = []
    for manifest in ordered:
        try:
            module = _import_plugin_module(manifest)
            cls = _find_plugin_subclass(module)
            instance_cfg = plugins_cfg.get(manifest.name, {}) or {}
            instance = cls(config=instance_cfg)
            # Bind name/version from manifest so subclasses don't have to
            # declare them themselves.
            instance.name = manifest.name
            instance.version = manifest.version
            if _mark_installed(manifest.name, marker):
                try:
                    instance.on_install()
                except Exception:
                    logger.exception(
                        "plugin %s on_install raised; continuing", manifest.name
                    )
            out.append(instance)
        except Exception:
            logger.exception("plugin %s failed to load; skipping", manifest.name)
    return out
