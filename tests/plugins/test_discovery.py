"""Plugin discovery walks bundled + user dirs, skips malformed entries."""

from __future__ import annotations

from pathlib import Path

from athena.plugins.discovery import discover


def _make_plugin(
    base: Path,
    name: str,
    *,
    toml_body: str | None = None,
    has_py: bool = True,
) -> Path:
    plugin_dir = base / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    if toml_body is not None:
        (plugin_dir / "plugin.toml").write_text(toml_body, encoding="utf-8")
    if has_py:
        (plugin_dir / "plugin.py").write_text("# placeholder\n", encoding="utf-8")
    return plugin_dir


def test_discovers_bundled_plugins(tmp_path: Path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    _make_plugin(
        bundled,
        "alpha",
        toml_body='[plugin]\nname = "alpha"\nversion = "0.1.0"\n',
    )
    manifests = discover(bundled_dir=bundled, user_dir=user)
    assert [m.name for m in manifests] == ["alpha"]


def test_discovers_user_plugins(tmp_path: Path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    _make_plugin(
        user,
        "beta",
        toml_body='[plugin]\nname = "beta"\nversion = "0.2.0"\n',
    )
    manifests = discover(bundled_dir=bundled, user_dir=user)
    assert [m.name for m in manifests] == ["beta"]


def test_discovers_both_in_bundled_then_user_order(tmp_path: Path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    _make_plugin(bundled, "a", toml_body='[plugin]\nname = "a"\nversion = "0.1.0"\n')
    _make_plugin(user, "z", toml_body='[plugin]\nname = "z"\nversion = "0.1.0"\n')
    manifests = discover(bundled_dir=bundled, user_dir=user)
    # Bundled before user. Within each root, alphabetical.
    assert [m.name for m in manifests] == ["a", "z"]


def test_skips_plugins_without_manifest(tmp_path: Path, caplog):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    _make_plugin(bundled, "no_toml", toml_body=None, has_py=True)
    with caplog.at_level("INFO"):
        manifests = discover(bundled_dir=bundled, user_dir=user)
    assert manifests == []
    assert any("no_toml" in r.message and "plugin.toml" in r.message for r in caplog.records)


def test_skips_plugins_without_plugin_py(tmp_path: Path, caplog):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    _make_plugin(
        bundled,
        "no_py",
        toml_body='[plugin]\nname = "no_py"\nversion = "0.1.0"\n',
        has_py=False,
    )
    with caplog.at_level("INFO"):
        manifests = discover(bundled_dir=bundled, user_dir=user)
    assert manifests == []
    assert any("no_py" in r.message and "plugin.py" in r.message for r in caplog.records)


def test_skips_malformed_manifest_with_log(tmp_path: Path, caplog):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    _make_plugin(bundled, "broken", toml_body='[plugin]\nversion = "0.1.0"\n')  # missing name
    with caplog.at_level("INFO"):
        manifests = discover(bundled_dir=bundled, user_dir=user)
    assert manifests == []
    assert any("broken" in r.message for r in caplog.records)


def test_skips_non_directory_entries(tmp_path: Path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "stray-file.txt").write_text("not a plugin", encoding="utf-8")
    _make_plugin(bundled, "real", toml_body='[plugin]\nname = "real"\nversion = "0.1.0"\n')
    manifests = discover(bundled_dir=bundled, user_dir=tmp_path / "user")
    assert [m.name for m in manifests] == ["real"]


def test_skips_dunder_directories(tmp_path: Path):
    """__pycache__ and similar must be ignored even if they accidentally
    contain plugin.toml + plugin.py."""
    bundled = tmp_path / "bundled"
    pycache = bundled / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "plugin.toml").write_text(
        '[plugin]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (pycache / "plugin.py").write_text("# nope\n", encoding="utf-8")
    manifests = discover(bundled_dir=bundled, user_dir=tmp_path / "user")
    assert manifests == []


def test_missing_dirs_return_empty(tmp_path: Path):
    """No bundled or user dir present → empty list, no exception."""
    manifests = discover(
        bundled_dir=tmp_path / "nope_bundled",
        user_dir=tmp_path / "nope_user",
    )
    assert manifests == []
