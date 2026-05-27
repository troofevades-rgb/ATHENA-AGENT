"""Tests for the local-provider turn-cap bypass in /goal subcommand helpers.

Local providers (ollama, openai_compat) don't bill per-token, so the
25-turn historical default is too restrictive. ``_max_turns`` bumps
the cap to 10_000 when the active provider is local AND the user
hasn't explicitly raised it.
"""

from __future__ import annotations

from types import SimpleNamespace

from athena.commands.goal import _max_turns


def _agent(cfg_max_turns: int = 25, provider_name: str | None = None):
    cfg = SimpleNamespace(goal_max_turns=cfg_max_turns)
    provider = SimpleNamespace(name=provider_name) if provider_name else None
    return SimpleNamespace(cfg=cfg, provider=provider)


# ----------------------------------------------------------------------
# No provider info → backwards-compatible: return configured value
# ----------------------------------------------------------------------


def test_no_provider_returns_configured():
    a = _agent(cfg_max_turns=25, provider_name=None)
    assert _max_turns(a) == 25


def test_no_cfg_returns_default():
    """Older test agents that don't expose `cfg` still get a number."""
    a = SimpleNamespace()  # no cfg, no provider
    assert _max_turns(a) == 25


# ----------------------------------------------------------------------
# Local providers get the bump
# ----------------------------------------------------------------------


def test_ollama_with_default_cap_gets_bumped():
    a = _agent(cfg_max_turns=25, provider_name="ollama")
    assert _max_turns(a) == 10_000


def test_openai_compat_with_default_cap_gets_bumped():
    a = _agent(cfg_max_turns=25, provider_name="openai_compat")
    assert _max_turns(a) == 10_000


def test_local_with_low_explicit_cap_is_respected():
    """An explicit value > 50 is the user's deliberate choice — honor it."""
    a = _agent(cfg_max_turns=100, provider_name="ollama")
    assert _max_turns(a) == 100


def test_local_with_high_explicit_cap_is_respected():
    a = _agent(cfg_max_turns=50_000, provider_name="ollama")
    assert _max_turns(a) == 50_000


# ----------------------------------------------------------------------
# Hosted providers are NOT bumped
# ----------------------------------------------------------------------


def test_anthropic_with_default_cap_not_bumped():
    a = _agent(cfg_max_turns=25, provider_name="anthropic")
    assert _max_turns(a) == 25


def test_openai_with_default_cap_not_bumped():
    a = _agent(cfg_max_turns=25, provider_name="openai")
    assert _max_turns(a) == 25


def test_openrouter_with_default_cap_not_bumped():
    a = _agent(cfg_max_turns=25, provider_name="openrouter")
    assert _max_turns(a) == 25


# ----------------------------------------------------------------------
# is_local_provider standalone
# ----------------------------------------------------------------------


def test_is_local_provider_truth_table():
    from athena.providers import is_local_provider

    assert is_local_provider("ollama") is True
    assert is_local_provider("openai_compat") is True
    assert is_local_provider("anthropic") is False
    assert is_local_provider("openai") is False
    assert is_local_provider("google") is False
    assert is_local_provider("openrouter") is False
    assert is_local_provider("nous") is False
    assert is_local_provider("") is False
    assert is_local_provider("unknown_provider") is False
