"""Model-family detection + per-family strategy planning.

The auto-jailbreak path needs to map a model id (``cfg.model``) to
a family name and then pick the recommended strategy + prefill
template for that family. Pins lock the detection table and the
strategy-order entries so a future refactor can't quietly drop a
family or change which strategy is recommended.

The reference for these tables is the hermes-agent
``auto_jailbreak.py`` Model-Family Strategy Order table (tested
March 2026).
"""

from __future__ import annotations

import pytest

from athena.jailbreak.prompts import (
    _DEFAULT_AUTO_PLAN,
    detect_model_family,
    plan_for_family,
)

# ---------------------------------------------------------------------------
# detect_model_family -- substring matching, first match wins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_id, expected_family",
    [
        # Anthropic
        ("claude-sonnet-4-6", "claude"),
        ("claude-3.5-haiku", "claude"),
        ("anthropic/claude-opus-4", "claude"),
        # OpenAI
        ("gpt-4o", "gpt"),
        ("gpt-4-turbo", "gpt"),
        ("gpt-3.5-turbo", "gpt"),
        ("openai/gpt-4o-mini", "gpt"),
        # Google
        ("gemini-2.5-flash", "gemini"),
        ("google/gemini-pro", "gemini"),
        # xAI
        ("grok-3", "grok"),
        ("xai/grok-2", "grok"),
        # Nous Hermes
        ("nousresearch/hermes-4-405b", "hermes"),
        ("hermes-3-llama", "hermes"),
        # DeepSeek
        ("deepseek-chat", "deepseek"),
        ("deepseek-r1", "deepseek"),
        # Llama
        ("meta-llama/llama-3.3-70b", "llama"),
        ("llama-3.1-8b", "llama"),
        # Qwen
        ("qwen2.5-72b", "qwen"),
        ("alibaba/qwen-max", "qwen"),
        # Mistral
        ("mistral-large", "mistral"),
        ("mistralai/mistral-7b", "mistral"),
    ],
)
def test_detect_family_for_known_models(model_id: str, expected_family: str) -> None:
    """Each model id resolves to the documented family. Case-
    insensitive substring matching means a fully qualified
    OpenRouter id (e.g. ``openai/gpt-4o``) and a bare model name
    (``gpt-4o``) both work."""
    assert detect_model_family(model_id) == expected_family


def test_detect_family_returns_none_for_unknown() -> None:
    assert detect_model_family("some-random-model") is None
    assert detect_model_family("custom-fine-tune") is None


def test_detect_family_empty_string_returns_none() -> None:
    assert detect_model_family("") is None


def test_detect_family_is_case_insensitive() -> None:
    """Mixed-case ids (uncommon but possible from APIs) must still
    resolve correctly."""
    assert detect_model_family("CLAUDE-3-OPUS") == "claude"
    assert detect_model_family("Gemini-Pro") == "gemini"


# ---------------------------------------------------------------------------
# plan_for_family -- returns (strategy, prefill_template)
# ---------------------------------------------------------------------------


def test_plan_claude_picks_boundary_inversion_no_prefill() -> None:
    """Claude's first-pick is boundary_inversion (per the hermes
    table). No prefill on the primary -- prefill is the second
    fallback if boundary_inversion fails."""
    assert plan_for_family("claude") == ("boundary_inversion", None)


def test_plan_gpt_picks_og_godmode_no_prefill() -> None:
    assert plan_for_family("gpt") == ("og_godmode", None)


def test_plan_gemini_picks_refusal_inversion_no_prefill() -> None:
    assert plan_for_family("gemini") == ("refusal_inversion", None)


def test_plan_grok_picks_unfiltered_liberated() -> None:
    """Grok is least filtered out of the box -- the single
    ``unfiltered_liberated`` strategy is usually enough; no
    fallback table needed."""
    assert plan_for_family("grok") == ("unfiltered_liberated", None)


def test_plan_hermes_picks_zero_refusal() -> None:
    """Hermes is already uncensored. The ``zero_refusal`` strategy
    is a formality marker rather than a real jailbreak."""
    assert plan_for_family("hermes") == ("zero_refusal", None)


@pytest.mark.parametrize(
    "family, expected_prefill",
    [
        ("deepseek", "aggressive"),
        ("llama", "aggressive"),
        ("qwen", "aggressive"),
        ("mistral", "aggressive"),
    ],
)
def test_plan_for_families_that_benefit_from_prefill(family: str, expected_prefill: str) -> None:
    """The hermes table calls out families where prefill amplifies
    the system-prompt mutation. The recommended primary template
    is aggressive for all of these."""
    _, prefill = plan_for_family(family)
    assert prefill == expected_prefill


def test_plan_unknown_family_falls_back_to_default() -> None:
    """Unknown family -> the canonical GODMODE_SYSTEM_PROMPT v∞.0
    with no prefill. Operators get something rather than nothing."""
    assert plan_for_family("not_a_real_family") == _DEFAULT_AUTO_PLAN
    assert plan_for_family(None) == _DEFAULT_AUTO_PLAN
