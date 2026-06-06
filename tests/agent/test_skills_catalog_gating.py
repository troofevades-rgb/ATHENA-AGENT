"""The skill catalog is injected into the system prompt only when the
"skills" toolset is in scope.

A lean-toolset caller (Discord voice, forks, the curator) that doesn't enable
"skills" has neither ``skills_list`` nor ``skill_view`` — so handing it a skill
catalog plus a "call skill_view to load one" instruction wastes prompt tokens
on an unactionable directive. The gate lives in ``Agent._build_system``
(athena/agent/lifecycle.py); ``enabled_toolsets is None`` (the normal/text
default) still shows the catalog.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from athena.agent.core import Agent
from athena.config import Config

if TYPE_CHECKING:
    from tests.conftest import SkillWriter

    from .conftest import FakeProvider


def _agent(
    fake_provider: FakeProvider, workspace: Path, enabled_toolsets: list[str] | None
) -> Agent:
    cfg = Config(model="fake-model", enabled_toolsets=enabled_toolsets)
    return Agent(cfg, workspace, provider=fake_provider)


def test_catalog_present_with_default_toolsets(
    fake_provider: FakeProvider, isolated_home: Path, workspace: Path, write_skill: SkillWriter
) -> None:
    # enabled_toolsets=None → all toolsets (text/normal sessions) → catalog shown.
    write_skill(isolated_home / ".athena" / "skills", "in-scope-skill")
    agent = _agent(fake_provider, workspace, None)
    assert "Skills available" in agent.messages[0]["content"]
    assert "in-scope-skill" in agent.messages[0]["content"]


def test_catalog_absent_when_skills_toolset_disabled(
    fake_provider: FakeProvider, isolated_home: Path, workspace: Path, write_skill: SkillWriter
) -> None:
    # A lean set WITHOUT "skills" (the old voice surface) → no catalog, no
    # dangling skill_view instruction.
    write_skill(isolated_home / ".athena" / "skills", "hidden-skill")
    agent = _agent(fake_provider, workspace, ["core", "memory", "recall", "web"])
    assert "Skills available" not in agent.messages[0]["content"]
    assert "hidden-skill" not in agent.messages[0]["content"]


def test_catalog_present_when_skills_toolset_enabled(
    fake_provider: FakeProvider, isolated_home: Path, workspace: Path, write_skill: SkillWriter
) -> None:
    # The new voice surface enables "skills" → catalog returns, now backed by
    # the skills_list / skill_view tools.
    write_skill(isolated_home / ".athena" / "skills", "voice-skill")
    agent = _agent(fake_provider, workspace, ["core", "memory", "recall", "web", "skills"])
    assert "Skills available" in agent.messages[0]["content"]
    assert "voice-skill" in agent.messages[0]["content"]
