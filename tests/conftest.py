"""Shared fixtures for skill tests.

``isolated_home`` redirects ``~`` to a temp path so tests can populate
``~/.athena/skills/`` without touching the developer's real home. ``write_skill``
is a tiny helper for fabricating SKILL.md files.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from athena.skills import loader
from athena.skills.frontmatter import SkillFrontmatter, serialize_frontmatter


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    # Python caches expanduser results; nudge Path.home() by patching it.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    # Body cache must not leak across tests.
    loader.invalidate_all()
    return home


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


SkillWriter = Callable[..., Path]


@pytest.fixture
def write_skill() -> SkillWriter:
    def _write(
        base: Path,
        name: str,
        *,
        description: str = "A test skill.",
        body: str = "",
        **fm_kwargs,
    ) -> Path:
        skill_dir = base / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        fm = SkillFrontmatter(name=name, description=description, **fm_kwargs)
        (skill_dir / "SKILL.md").write_text(serialize_frontmatter(fm, body), encoding="utf-8")
        return skill_dir

    return _write
