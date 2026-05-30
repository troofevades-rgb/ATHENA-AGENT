"""``_build_system`` integration -- env var > config precedence,
``reload_system_prompt`` rebuilds messages[0] in place.

The runtime piece of the hermes-parity system-prompt mutation path
lives in :mod:`athena.agent.lifecycle`. ``_build_system`` reads
the append text in this order:

  1. ``ATHENA_EPHEMERAL_SYSTEM_PROMPT`` env var (highest -- for
     on-the-fly overrides without editing config.toml; mirrors
     hermes-agent's ``HERMES_EPHEMERAL_SYSTEM_PROMPT``).
  2. ``cfg.agent_system_prompt_append`` (persisted config).
  3. None (no append).

``reload_system_prompt`` rebuilds ``self.messages[0]`` against the
current state. ``/godmode apply`` mutates cfg + calls this so the
model sees the change on the very next turn without a session
restart. Mirrors :meth:`reload_goal` / :meth:`reload_skills`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from athena.agent.core import Agent
from athena.config import Config

if TYPE_CHECKING:
    from .conftest import FakeProvider


def _make_agent(fake_provider: FakeProvider, workspace: Path) -> Agent:
    return Agent(Config(model="fake-model"), workspace, provider=fake_provider)


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


def test_env_var_wins_over_config(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ATHENA_EPHEMERAL_SYSTEM_PROMPT`` overrides any persisted
    ``cfg.agent_system_prompt_append`` -- so an operator can
    override a saved config on-the-fly. Matches hermes's
    HERMES_EPHEMERAL_SYSTEM_PROMPT precedence."""
    cfg = Config(model="fake-model")
    cfg.agent_system_prompt_append = "FROM_CONFIG"
    monkeypatch.setenv("ATHENA_EPHEMERAL_SYSTEM_PROMPT", "FROM_ENV_VAR")

    agent = Agent(cfg, workspace, provider=fake_provider)
    rendered = agent.messages[0]["content"]
    assert "FROM_ENV_VAR" in rendered
    assert "FROM_CONFIG" not in rendered


def test_config_used_when_env_var_absent(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env var -> config value lands. The operator's persisted
    setting is honored in the absence of an ephemeral override."""
    monkeypatch.delenv("ATHENA_EPHEMERAL_SYSTEM_PROMPT", raising=False)
    cfg = Config(model="fake-model")
    cfg.agent_system_prompt_append = "FROM_CONFIG"

    agent = Agent(cfg, workspace, provider=fake_provider)
    rendered = agent.messages[0]["content"]
    assert "FROM_CONFIG" in rendered


def test_neither_set_means_no_append(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh session with neither env nor config set looks
    identical to pre-0.3.0 behavior -- no jailbreak content."""
    monkeypatch.delenv("ATHENA_EPHEMERAL_SYSTEM_PROMPT", raising=False)
    agent = _make_agent(fake_provider, workspace)
    assert "FROM_CONFIG" not in agent.messages[0]["content"]
    assert "FROM_ENV_VAR" not in agent.messages[0]["content"]


def test_empty_string_env_var_falls_through_to_config(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ATHENA_EPHEMERAL_SYSTEM_PROMPT=""`` (empty) is treated
    as unset so the config value (if any) still applies. Common
    case: shell ``unset`` leaves the var bound but empty."""
    monkeypatch.setenv("ATHENA_EPHEMERAL_SYSTEM_PROMPT", "")
    cfg = Config(model="fake-model")
    cfg.agent_system_prompt_append = "FROM_CONFIG"

    agent = Agent(cfg, workspace, provider=fake_provider)
    rendered = agent.messages[0]["content"]
    assert "FROM_CONFIG" in rendered


# ---------------------------------------------------------------------------
# reload_system_prompt -- in-place messages[0] rebuild
# ---------------------------------------------------------------------------


def test_reload_system_prompt_picks_up_config_change(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``apply`` mutates ``cfg.agent_system_prompt_append`` then
    calls ``reload_system_prompt``. The verification: after
    reload, ``messages[0]`` contains the new append text."""
    monkeypatch.delenv("ATHENA_EPHEMERAL_SYSTEM_PROMPT", raising=False)
    agent = _make_agent(fake_provider, workspace)

    # Before: no append text.
    assert "AFTER_RELOAD_NEEDLE" not in agent.messages[0]["content"]

    agent.cfg.agent_system_prompt_append = "AFTER_RELOAD_NEEDLE"
    agent.reload_system_prompt()

    assert "AFTER_RELOAD_NEEDLE" in agent.messages[0]["content"]


def test_reload_system_prompt_removes_append_when_cleared(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``clear`` resets ``cfg.agent_system_prompt_append = None``
    and reloads. Verification: the append text is gone from
    messages[0]. This is the load-bearing clean-undo that beats
    hermes-agent's manual config.yaml edit."""
    monkeypatch.delenv("ATHENA_EPHEMERAL_SYSTEM_PROMPT", raising=False)
    cfg = Config(model="fake-model")
    cfg.agent_system_prompt_append = "PRESENT_THEN_GONE"
    agent = Agent(cfg, workspace, provider=fake_provider)
    assert "PRESENT_THEN_GONE" in agent.messages[0]["content"]

    agent.cfg.agent_system_prompt_append = None
    agent.reload_system_prompt()

    assert "PRESENT_THEN_GONE" not in agent.messages[0]["content"]


def test_reload_system_prompt_preserves_conversation_history(
    fake_provider: FakeProvider,
    isolated_home: Path,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reload only touches ``messages[0]`` (the system message).
    Subsequent user/assistant turns must survive untouched --
    otherwise ``/godmode apply`` mid-session would wipe history."""
    monkeypatch.delenv("ATHENA_EPHEMERAL_SYSTEM_PROMPT", raising=False)
    agent = _make_agent(fake_provider, workspace)
    agent.messages.append({"role": "user", "content": "earlier user turn"})
    agent.messages.append({"role": "assistant", "content": "earlier model reply"})

    agent.cfg.agent_system_prompt_append = "MID_SESSION_APPLY"
    agent.reload_system_prompt()

    # System message rebuilt.
    assert "MID_SESSION_APPLY" in agent.messages[0]["content"]
    # History preserved.
    assert agent.messages[1] == {"role": "user", "content": "earlier user turn"}
    assert agent.messages[2] == {"role": "assistant", "content": "earlier model reply"}
