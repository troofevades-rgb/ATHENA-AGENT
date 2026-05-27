"""Shared fixtures for skill tests.

``isolated_home`` redirects ``~`` to a temp path so tests can populate
``~/.athena/skills/`` without touching the developer's real home. ``write_skill``
is a tiny helper for fabricating SKILL.md files.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from athena.safety.path_security import set_workspace as _path_security_set_workspace
from athena.skills import loader
from athena.skills.frontmatter import SkillFrontmatter, serialize_frontmatter


@pytest.fixture(autouse=True)
def _path_security_workspace(tmp_path: Path) -> None:
    """Point path_security at tmp_path for every test.

    Without this, tests that exercise athena.tools.file_ops would block
    on the interactive approval prompt because tmp_path is outside the
    process cwd (the project root). Tests that legitimately need to
    operate outside tmp_path wrap their call in
    ``athena.safety.path_security.allow_external()``.
    """
    _path_security_set_workspace(tmp_path)


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    # Python caches expanduser results; nudge Path.home() by patching it.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    # ``athena.config.CONFIG_DIR`` is computed at module import time
    # (``Path.home() / ".athena"`` — frozen as a module-level constant).
    # Monkeypatching ``Path.home`` AFTER import doesn't change CONFIG_DIR,
    # so anything that reads via ``profile_dir(...)`` without a ``home=``
    # override still hits the developer's real ~/.athena. That made
    # tests like ``test_anthropic_provider_gets_cache_markers`` read the
    # user's real ``goal_state.json``, and when it had an active goal
    # with ``max_turns=10000`` the agent looped 10k turns until pytest
    # timed it out. Redirect every CONFIG_DIR-derived constant in
    # athena.config so subsystems reading via profile_dir() see the tmp
    # home too.
    import athena.config as _athena_config
    tmp_config_dir = home / ".athena"
    monkeypatch.setattr(_athena_config, "CONFIG_DIR", tmp_config_dir)
    monkeypatch.setattr(_athena_config, "CONFIG_PATH", tmp_config_dir / "config.toml")
    monkeypatch.setattr(_athena_config, "SESSIONS_DIR", tmp_config_dir / "sessions")
    monkeypatch.setattr(_athena_config, "USER_MCP_PATH", tmp_config_dir / "mcp.json")
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
