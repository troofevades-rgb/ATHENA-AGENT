"""plugin.toml parser tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from ocode.plugins.manifest import ManifestError, PluginManifest, parse_manifest


def write_manifest(tmp_path: Path, body: str) -> Path:
    target = tmp_path / "plugin.toml"
    target.write_text(body, encoding="utf-8")
    return target


def test_parses_minimal_manifest(tmp_path: Path):
    p = write_manifest(tmp_path, '[plugin]\nname = "mini"\nversion = "0.1.0"\n')
    m = parse_manifest(p)
    assert m.name == "mini"
    assert m.version == "0.1.0"
    assert m.description == ""
    assert m.enabled_by_default is True
    assert m.depends_on == []
    assert m.config_schema is None
    assert m.path == tmp_path


def test_parses_full_manifest(tmp_path: Path):
    p = write_manifest(
        tmp_path,
        """
[plugin]
name = "full"
version = "2.3.4"
description = "A demonstration manifest with every supported field."
enabled_by_default = false
depends_on = ["one", "two"]
config_schema = { type = "object" }
""",
    )
    m = parse_manifest(p)
    assert m.name == "full"
    assert m.version == "2.3.4"
    assert m.description.startswith("A demonstration")
    assert m.enabled_by_default is False
    assert m.depends_on == ["one", "two"]
    assert m.config_schema == {"type": "object"}


def test_rejects_missing_name(tmp_path: Path):
    p = write_manifest(tmp_path, '[plugin]\nversion = "0.1.0"\n')
    with pytest.raises(ManifestError, match="missing 'name'"):
        parse_manifest(p)


def test_rejects_missing_version(tmp_path: Path):
    p = write_manifest(tmp_path, '[plugin]\nname = "noversion"\n')
    with pytest.raises(ManifestError, match="missing 'version'"):
        parse_manifest(p)


def test_rejects_missing_plugin_section(tmp_path: Path):
    p = write_manifest(tmp_path, '[other]\nname = "x"\n')
    with pytest.raises(ManifestError, match=r"missing \[plugin\] section"):
        parse_manifest(p)


def test_rejects_invalid_toml(tmp_path: Path):
    p = write_manifest(tmp_path, '[plugin]\nname = "missing close quote\n')
    with pytest.raises(ManifestError, match="invalid TOML"):
        parse_manifest(p)


def test_rejects_depends_on_not_a_list_of_strings(tmp_path: Path):
    p = write_manifest(
        tmp_path,
        '[plugin]\nname = "x"\nversion = "0.1.0"\ndepends_on = "not-a-list"\n',
    )
    with pytest.raises(ManifestError, match="'depends_on' must be a list"):
        parse_manifest(p)


def test_path_points_to_plugin_directory(tmp_path: Path):
    """The ``path`` field is the manifest's parent dir, not the manifest itself."""
    sub = tmp_path / "my_plugin"
    sub.mkdir()
    p = write_manifest(sub, '[plugin]\nname = "x"\nversion = "0.1.0"\n')
    m = parse_manifest(p)
    assert m.path == sub
    assert m.path is not None
    # Caller can join with plugin.py to locate the module:
    assert (m.path / "plugin.py").parent == sub
