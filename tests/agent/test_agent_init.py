"""Agent construction + config wiring (T1-04.3)."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from athena.agent.core import Agent
from athena.config import Config

if TYPE_CHECKING:
    from .conftest import FakeProvider


def _make_agent(
    fake_provider: FakeProvider,
    workspace: Path,
    **cfg_overrides,
) -> Agent:
    cfg = Config(model="fake-model")
    for k, v in cfg_overrides.items():
        setattr(cfg, k, v)
    return Agent(cfg, workspace, provider=fake_provider)


def test_agent_construction_is_offline(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """Constructing the Agent must NOT call the provider's network
    methods. The provider is only invoked at run_turn time."""
    agent = _make_agent(fake_provider, workspace)
    # FakeProvider would have recorded any stream_chat call.
    assert fake_provider.call_history == []
    # And the model field is unchanged from cfg (no routing/network
    # roundtrip on construct).
    assert agent.model == "fake-model"
    # Sanity: the agent has a session id (UUIDv7 minted at __init__).
    assert agent.session_id is not None
    assert len(agent.session_id) > 0


def test_agent_loads_athena_md_from_workspace(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """When ``ATHENA.md`` is present at the workspace root, the agent
    incorporates it into the system prompt."""
    athena_md = workspace / "ATHENA.md"
    sentinel = "## Project hint\nUse the foo-utils package, never bar."
    athena_md.write_text(sentinel, encoding="utf-8")

    agent = _make_agent(fake_provider, workspace)

    # System prompt is messages[0]['content']. The exact location of
    # the project-doc block is an implementation detail of
    # build_system_prompt; we just assert the sentinel landed in it.
    assert agent.messages, "agent has no messages after init"
    system_text = agent.messages[0].get("content") or ""
    assert sentinel in system_text or "foo-utils" in system_text, (
        f"ATHENA.md content not visible in system prompt; "
        f"first 200 chars: {system_text[:200]!r}"
    )


def test_agent_respects_enabled_toolsets(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
) -> None:
    """``cfg.enabled_toolsets = ["file"]`` restricts the visible tool
    list to just the ``file`` toolset; ``shell`` (Bash) is hidden."""
    from athena import tools

    # First baseline: no restriction → both Read and Bash are visible.
    full_catalog = {
        t.name for t in tools.all_tools(disabled=[])
    }
    assert "Read" in full_catalog
    assert "Bash" in full_catalog

    # Now restrict to file toolset only. The agent reads
    # enabled_toolsets through tools.ollama_schema() in _stream_one;
    # we exercise the same helper directly.
    schema = tools.ollama_schema(
        enabled_toolsets=["file"], disabled=[],
    )
    names = {entry["function"]["name"] for entry in schema}
    assert "Read" in names
    assert "Bash" not in names, (
        f"Bash should be filtered out by enabled_toolsets=['file']; "
        f"got names: {sorted(names)}"
    )

    # Bonus: confirm the agent constructs cleanly with the restriction.
    agent = _make_agent(
        fake_provider, workspace, enabled_toolsets=["file"],
    )
    assert agent.cfg.enabled_toolsets == ["file"]
