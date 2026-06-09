"""Helpers for building a synthetic Hermes home tree under tmp_path."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml


def _write_hermes_skill(
    base: Path,
    name: str,
    *,
    description: str = "A hermes skill.",
    archived: bool = False,
    body: str = "Hermes skill body.\n",
    extra: dict | None = None,
) -> Path:
    parent = base / "skills"
    if archived:
        parent = parent / ".archive"
    parent.mkdir(parents=True, exist_ok=True)
    skill_dir = parent / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    fm = {"name": name, "description": description}
    if extra:
        fm.update(extra)
    yaml_text = yaml.safe_dump(fm, sort_keys=False)
    (skill_dir / "SKILL.md").write_text(f"---\n{yaml_text}---\n{body}", encoding="utf-8")
    return skill_dir


@pytest.fixture
def hermes_skill_factory() -> Callable[..., Path]:
    return _write_hermes_skill


@pytest.fixture
def hermes_source(tmp_path: Path) -> Path:
    """A fresh empty Hermes home that tests can populate."""
    src = tmp_path / "hermes-home"
    src.mkdir()
    return src


@pytest.fixture
def athena_dest(tmp_path: Path) -> Path:
    dst = tmp_path / "athena-home"
    dst.mkdir()
    return dst


@pytest.fixture
def migration_report(tmp_path: Path):
    from athena.migration.report import Report

    return Report(path=tmp_path / "report")
