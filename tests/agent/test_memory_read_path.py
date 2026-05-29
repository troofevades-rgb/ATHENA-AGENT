"""R2 stage 2 -- Agent reads MEMORY.md via the profile-keyed provider.

The agent's ``_build_system`` block at ``agent/core.py:843`` was
flipped from the workspace-keyed legacy API
(``memory.load_memory_index(workspace)``) to the provider-backed
``memory.store.load_index(profile, workspace=workspace)``. The
former workspace dimension is preserved by the provider's
``workspace=`` kwarg (R2 stage 1).

These tests pin both halves of the compatibility contract:

  - New writes (via ``store.write_entry``) under (profile, workspace)
    show up in the agent's system prompt.
  - Existing users with a legacy
    ``~/.athena/projects/<slug>/memory/MEMORY.md`` still see it
    injected -- the read site falls back when the new location is
    empty. The fallback gets removed at R2 stage 5 (after the
    flag-gated stage-4 data migration ships and operators dogfood).
  - When BOTH locations have content, the new (provider) path
    wins -- otherwise a half-migrated state would silently surface
    the stale legacy copy.
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
    """Pin a short, deterministic workspace slug across both stores.

    The real :meth:`BuiltinFileProvider.workspace_slug` and the legacy
    :func:`athena.memory._slugify` both embed the full resolved
    workspace path. Pytest's tmp_path roots on Windows are already
    ~100 characters deep; adding either slug bumps the resulting
    directory over MAX_PATH (260 chars). Tests that don't care about
    slug shape monkey-patch this fixture in -- the new provider
    (this file's writer) and the legacy reader (the agent's fallback
    path in core.py) both route through the same patched function so
    the on-disk layouts agree.

    Slug stability against the real algorithm is pinned separately in
    ``tests/memory/test_workspace_dimension.py``.
    """
    slug = "test-ws"
    monkeypatch.setattr(
        BuiltinFileProvider,
        "workspace_slug",
        staticmethod(lambda _ws: slug),
    )
    monkeypatch.setattr("athena.memory._slugify", lambda _ws: slug)
    # ``athena.memory.PROJECTS_DIR`` is computed at module import time
    # from the pre-patch ``athena.config.CONFIG_DIR``, so the
    # ``isolated_home`` fixture's CONFIG_DIR patch doesn't reach it.
    # Repoint it now so legacy reads land under the tmp home.
    import athena.config as _cfg
    import athena.memory as _mem
    monkeypatch.setattr(_mem, "PROJECTS_DIR", _cfg.CONFIG_DIR / "projects")
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
# Primary path: provider-backed MEMORY.md lands in the system prompt
# ---------------------------------------------------------------------------


def test_provider_memory_appears_in_system_prompt(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    short_slug: str,
) -> None:
    """Writing a memory via the new profile+workspace-keyed provider
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
        f"new-path memory not visible in system prompt; first 400 chars: {text[:400]!r}"
    )


# ---------------------------------------------------------------------------
# Compatibility fallback: legacy ~/.athena/projects/<slug>/memory/ MEMORY.md
# ---------------------------------------------------------------------------


def test_legacy_workspace_memory_still_loads(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    short_slug: str,
) -> None:
    """An existing user with a workspace-keyed legacy MEMORY.md at
    ``~/.athena/projects/<slug>/memory/MEMORY.md`` keeps getting it
    injected until the stage-4 data migrator has run. Without this
    fallback, R2 stage 2 would be a user-visible regression."""
    legacy_dir = (
        isolated_home / ".athena" / "projects" / short_slug / "memory"
    )
    legacy_dir.mkdir(parents=True)
    legacy_index = legacy_dir / "MEMORY.md"
    legacy_index.write_text(
        "# MEMORY index\n\n- [legacy_pin](file.md) — user: legacy-only sentinel\n",
        encoding="utf-8",
    )

    agent = _make_agent(fake_provider, workspace)

    text = _system_text(agent)
    assert "legacy_pin" in text or "legacy-only sentinel" in text, (
        f"legacy MEMORY.md not visible after R2 stage 2; "
        f"first 400 chars: {text[:400]!r}"
    )


# ---------------------------------------------------------------------------
# When both exist, new (provider) wins
# ---------------------------------------------------------------------------


def test_provider_wins_over_legacy_when_both_present(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    short_slug: str,
) -> None:
    """If the operator has already migrated some memories to the new
    profile-keyed location, partial overlap with the legacy location
    must not let the stale legacy index override the fresh one. The
    read site checks new first, only falls back on None."""
    # New location has a marker.
    write_entry(
        "default",
        filename="new.md",
        name="new_marker",
        description="from-new-path",
        type="user",
        body="b",
        write_origin="foreground",
        workspace=workspace,
    )
    # Legacy location has a different marker.
    legacy_dir = (
        isolated_home / ".athena" / "projects" / short_slug / "memory"
    )
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "MEMORY.md").write_text(
        "# MEMORY index\n\n- [old_marker](old.md) — user: from-legacy-path\n",
        encoding="utf-8",
    )

    agent = _make_agent(fake_provider, workspace)

    text = _system_text(agent)
    assert "new_marker" in text or "from-new-path" in text, (
        "new (provider) path must win when both stores have content"
    )
    assert "old_marker" not in text and "from-legacy-path" not in text, (
        "legacy index must not appear once the new path has content"
    )
