"""load_config section-header footgun guard (_validate_section_placement).

A bare key written after a ``[section]`` header is folded into that
section by TOML, silently dropping a value the user meant for top
level. The validator catches a known top-level field appearing inside
a fixed-schema section.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from athena import config as cfgmod
from athena.config import Config, _validate_section_placement, load_config


def _cfg() -> Config:
    return Config()


# ---- direct unit tests on the validator --------------------------------


def test_misplaced_top_level_key_under_section_raises(tmp_path: Path) -> None:
    # 'model' is a top-level Config field, not a SkillsConfig field.
    data = {"skills": {"autoload": True, "model": "oops"}}
    with pytest.raises(ValueError) as ei:
        _validate_section_placement(data, _cfg(), tmp_path / "config.toml")
    msg = str(ei.value)
    assert "'model'" in msg
    assert "[skills]" in msg


def test_legit_section_does_not_raise(tmp_path: Path) -> None:
    data = {"skills": {"autoload": True, "autoload_interval": 1.0}}
    _validate_section_placement(data, _cfg(), tmp_path / "config.toml")  # no raise


def test_top_level_field_at_top_level_is_fine(tmp_path: Path) -> None:
    data = {"model": "x", "skills": {"autoload": True}}
    _validate_section_placement(data, _cfg(), tmp_path / "config.toml")  # no raise


def test_free_form_sections_skipped(tmp_path: Path) -> None:
    # plugins/providers accept arbitrary sub-keys (incl. ones that happen
    # to match top-level field names) — must never be flagged.
    data = {
        "plugins": {"enabled": {"shell_hook": True}, "model": "noflag"},
        "providers": {"routing": {"foo": "bar"}, "model": "noflag"},
    }
    _validate_section_placement(data, _cfg(), tmp_path / "config.toml")  # no raise


def test_unknown_table_not_policed(tmp_path: Path) -> None:
    data = {"totally_unknown": {"model": "x"}}
    _validate_section_placement(data, _cfg(), tmp_path / "config.toml")  # no raise


# ---- end-to-end through load_config, incl. line number -----------------


def _patch_config_dir(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(cfgmod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(cfgmod, "SESSIONS_DIR", tmp_path / "sessions")
    return tmp_path / "config.toml"


def test_load_config_raises_with_file_and_line(monkeypatch, tmp_path: Path) -> None:
    path = _patch_config_dir(monkeypatch, tmp_path)
    path.write_text(
        'model = "top"\n\n[skills]\nautoload = true\nmodel = "nested-by-mistake"\n',  # line 5
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as ei:
        load_config()
    msg = str(ei.value)
    assert "config.toml:5" in msg
    assert "[skills]" in msg


def test_load_config_clean_file_loads(monkeypatch, tmp_path: Path) -> None:
    path = _patch_config_dir(monkeypatch, tmp_path)
    path.write_text(
        'model = "top"\nauto_approve_tools = false\n\n[skills]\nautoload = true\n',
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.model == "top"
