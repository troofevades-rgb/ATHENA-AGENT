"""Plugin loader: imports modules dynamically, topo-sorts, handles cycles."""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.plugins.loader import (
    PluginDependencyError,
    _toposort,
    load_plugins,
)
from athena.plugins.manifest import PluginManifest


def _make_plugin_files(
    base: Path,
    name: str,
    *,
    plugin_body: str | None = None,
    enabled_by_default: bool = True,
    depends_on: list[str] | None = None,
) -> PluginManifest:
    plugin_dir = base / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    if plugin_body is None:
        plugin_body = f"""
from athena.plugins.base import Plugin
class TestPlugin(Plugin):
    INSTANTIATED_FOR = "{name}"
"""
    (plugin_dir / "plugin.py").write_text(plugin_body, encoding="utf-8")
    return PluginManifest(
        name=name,
        version="0.1.0",
        enabled_by_default=enabled_by_default,
        depends_on=depends_on or [],
        path=plugin_dir,
    )


def test_instantiates_plugin_subclass(tmp_path: Path):
    m = _make_plugin_files(tmp_path, "alpha")
    plugins = load_plugins([m], config={}, installed_marker=tmp_path / ".installed")
    assert len(plugins) == 1
    assert plugins[0].name == "alpha"
    assert plugins[0].version == "0.1.0"


def test_loader_passes_per_plugin_config(tmp_path: Path):
    m = _make_plugin_files(tmp_path, "alpha")
    plugins = load_plugins(
        [m],
        config={"plugins": {"alpha": {"key": "value"}}},
        installed_marker=tmp_path / ".installed",
    )
    assert plugins[0].config == {"key": "value"}


def test_topological_sort_respects_depends_on(tmp_path: Path):
    """A plugin that depends on another must load AFTER its dep."""
    a = _make_plugin_files(tmp_path, "a", depends_on=[])
    b = _make_plugin_files(tmp_path, "b", depends_on=["a"])
    c = _make_plugin_files(tmp_path, "c", depends_on=["b"])
    plugins = load_plugins(
        [c, b, a],  # deliberately reversed input order
        config={},
        installed_marker=tmp_path / ".installed",
    )
    assert [p.name for p in plugins] == ["a", "b", "c"]


def test_detects_dependency_cycle():
    a = PluginManifest(name="a", version="0.1.0", depends_on=["b"], path=Path("/tmp/a"))
    b = PluginManifest(name="b", version="0.1.0", depends_on=["a"], path=Path("/tmp/b"))
    with pytest.raises(PluginDependencyError, match="cycle"):
        _toposort([a, b])


def test_self_dependency_is_a_cycle():
    a = PluginManifest(name="a", version="0.1.0", depends_on=["a"], path=Path("/tmp/a"))
    with pytest.raises(PluginDependencyError, match="cycle"):
        _toposort([a])


def test_missing_dependency_is_tolerated():
    """A plugin depending on a missing plugin still loads — the dep just
    isn't enforced. (Real athena flow: that dep may be installed later.)"""
    a = PluginManifest(name="a", version="0.1.0", depends_on=["not-installed"], path=Path("/tmp/a"))
    ordered = _toposort([a])
    assert [m.name for m in ordered] == ["a"]


def test_disabled_plugins_skipped(tmp_path: Path):
    a = _make_plugin_files(tmp_path, "a", enabled_by_default=True)
    b = _make_plugin_files(tmp_path, "b", enabled_by_default=False)
    plugins = load_plugins([a, b], config={}, installed_marker=tmp_path / ".installed")
    assert [p.name for p in plugins] == ["a"]


def test_config_override_enables_disabled_plugin(tmp_path: Path):
    m = _make_plugin_files(tmp_path, "x", enabled_by_default=False)
    plugins = load_plugins(
        [m],
        config={"plugins": {"enabled": {"x": True}}},
        installed_marker=tmp_path / ".installed",
    )
    assert [p.name for p in plugins] == ["x"]


def test_config_override_disables_default_enabled_plugin(tmp_path: Path):
    m = _make_plugin_files(tmp_path, "y", enabled_by_default=True)
    plugins = load_plugins(
        [m],
        config={"plugins": {"enabled": {"y": False}}},
        installed_marker=tmp_path / ".installed",
    )
    assert plugins == []


def test_on_install_called_only_on_first_activation(tmp_path: Path):
    install_calls_dir = tmp_path / "install_calls"
    install_calls_dir.mkdir()

    plugin_body = f"""
from pathlib import Path
from athena.plugins.base import Plugin

class Tracker(Plugin):
    def on_install(self):
        Path({str(install_calls_dir)!r}, '{{}}'.format(self.name)).touch()
"""
    m = _make_plugin_files(tmp_path, "tracker", plugin_body=plugin_body)
    marker = tmp_path / ".installed"

    # First load → on_install fires.
    load_plugins([m], config={}, installed_marker=marker)
    assert (install_calls_dir / "tracker").exists()

    # Second load → on_install must NOT fire again (file count stays 1).
    (install_calls_dir / "tracker").unlink()
    load_plugins([m], config={}, installed_marker=marker)
    assert not (install_calls_dir / "tracker").exists()


def test_module_with_no_plugin_subclass_is_skipped(tmp_path: Path, caplog):
    m = _make_plugin_files(
        tmp_path,
        "no_subclass",
        plugin_body="# intentionally no Plugin subclass\nX = 1\n",
    )
    with caplog.at_level("ERROR"):
        plugins = load_plugins([m], config={}, installed_marker=tmp_path / ".installed")
    assert plugins == []
    assert any("no_subclass" in r.message for r in caplog.records)


def test_module_with_multiple_plugin_subclasses_is_skipped(tmp_path: Path, caplog):
    body = """
from athena.plugins.base import Plugin
class A(Plugin): pass
class B(Plugin): pass
"""
    m = _make_plugin_files(tmp_path, "two_classes", plugin_body=body)
    with caplog.at_level("ERROR"):
        plugins = load_plugins([m], config={}, installed_marker=tmp_path / ".installed")
    assert plugins == []
    assert any("two_classes" in r.message for r in caplog.records)


def test_name_and_version_rebound_from_manifest(tmp_path: Path):
    """Subclasses that hard-code name='wrong' must get overridden by manifest."""
    body = """
from athena.plugins.base import Plugin
class P(Plugin):
    name = "wrong"
    version = "wrong"
"""
    m = _make_plugin_files(tmp_path, "real_name", plugin_body=body)
    plugins = load_plugins([m], config={}, installed_marker=tmp_path / ".installed")
    assert plugins[0].name == "real_name"
    assert plugins[0].version == "0.1.0"
