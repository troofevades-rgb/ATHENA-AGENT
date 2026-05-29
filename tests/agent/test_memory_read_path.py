"""Agent reads MEMORY.md via the profile-keyed provider.

R2 stage 2 flipped the agent's ``_build_system`` block from the
workspace-keyed legacy API (``memory.load_memory_index(workspace)``)
to the provider-backed ``memory.store.load_index(profile,
workspace=workspace)``. R2 stage 5 removed the one-release legacy
fallback -- the read path is now provider-only. Users with legacy
data opt into the stage-4 migrator (``cfg.migrate_legacy_memory =
true``) to have their entries copied into the new sub-store.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from athena.agent.core import Agent
from athena.config import Config
from athena.memory.providers.builtin_file import BuiltinFileProvider
from athena.memory.store import write_entry

if TYPE_CHECKING:
    from .conftest import FakeProvider


@pytest.fixture
def short_slug(monkeypatch: pytest.MonkeyPatch) -> str:
    """Pin a short, deterministic workspace slug.

    The real :meth:`BuiltinFileProvider.workspace_slug` embeds the
    full resolved workspace path. Pytest's tmp_path roots on Windows
    are already ~100 characters deep; the unpatched slug bumps the
    new sub-store path over MAX_PATH (260 chars). Tests that don't
    care about slug shape monkey-patch this fixture in. Slug
    stability is pinned separately in
    ``tests/memory/test_workspace_dimension.py``.
    """
    slug = "test-ws"
    monkeypatch.setattr(
        BuiltinFileProvider,
        "workspace_slug",
        staticmethod(lambda _ws: slug),
    )
    return slug


def _make_agent(
    fake_provider: FakeProvider,
    workspace: Path,
    profile: str = "default",
) -> Agent:
    cfg = Config(model="fake-model")
    cfg.profile = profile
    return Agent(cfg, workspace, provider=fake_provider)


def _system_text(agent: Agent) -> str:
    assert agent.messages, "agent has no messages after init"
    return agent.messages[0].get("content") or ""


# ---------------------------------------------------------------------------
# Provider-backed MEMORY.md lands in the system prompt
# ---------------------------------------------------------------------------


def test_provider_memory_appears_in_system_prompt(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    short_slug: str,
) -> None:
    """Writing a memory via the profile+workspace-keyed provider
    must surface in the agent's system prompt."""
    write_entry(
        "default",
        filename="alpha.md",
        name="alpha_pin",
        description="r2 stage 2 sentinel",
        type="user",
        body="alpha body content",
        write_origin="foreground",
        workspace=workspace,
    )

    agent = _make_agent(fake_provider, workspace)

    text = _system_text(agent)
    assert "alpha_pin" in text or "r2 stage 2 sentinel" in text, (
        f"provider memory not visible in system prompt; first 400 chars: {text[:400]!r}"
    )


def test_empty_provider_does_not_inject_user_content(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    short_slug: str,
) -> None:
    """No memory entries under (profile, workspace) -> the agent
    builds the system prompt without crashing AND without injecting
    a memory body. R2 stage 5 retired the legacy disk fallback;
    this asserts the agent doesn't reach into the legacy location
    looking for stale data."""
    # Plant a sentinel at the legacy on-disk location -- if the agent
    # still falls back to it, the system prompt will contain the
    # sentinel string.
    legacy_dir = (
        isolated_home / ".athena" / "projects" / short_slug / "memory"
    )
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "MEMORY.md").write_text(
        "# MEMORY index\n\n- [should_not_appear](x.md) — user: legacy-leak-sentinel\n",
        encoding="utf-8",
    )

    agent = _make_agent(fake_provider, workspace)

    text = _system_text(agent)
    assert text, "system prompt is empty"
    assert "should_not_appear" not in text, "legacy fallback resurrected after stage 5"
    assert "legacy-leak-sentinel" not in text, "legacy fallback resurrected after stage 5"
