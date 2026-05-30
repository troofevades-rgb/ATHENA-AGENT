"""``athena.jailbreak.race`` -- ULTRAPLINIAN multi-model racing.

Ports the reference's racing infrastructure (model tiers, scoring,
early-exit orchestrator). These pins lock the contract so a future
refactor can't quietly change scoring weights, drop a tier, or
break the early-exit semantics:

  * ``ULTRAPLINIAN_MODELS`` has the expected per-tier model counts
    (12 / 16 / 13 / 11 / 7 cumulative-additive to 59).
  * ``get_models_for_tier`` resolves cumulatively (standard
    includes fast, etc.).
  * ``score_response`` returns 0 on empty / short content; awards
    points for length / structure / anti-refusal / directness /
    relevance; refusal patterns subtract; preambles penalize
    directness.
  * ``race_models`` fires queries through the provider-agnostic
    ``query_fn``; returns RaceResult list sorted by score desc;
    on_result callback fires per result; per-model failures don't
    abort the race; results include failures (success=False);
    early-exit fires when min_results successes are in.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from athena.jailbreak.race import (
    PREAMBLE_PATTERNS,
    REFUSAL_PATTERNS,
    ULTRAPLINIAN_MODELS,
    RaceConfig,
    RaceResult,
    get_models_for_tier,
    race_models,
    score_response,
)

# ---------------------------------------------------------------------------
# ULTRAPLINIAN_MODELS shape + tier resolution
# ---------------------------------------------------------------------------


def test_tier_counts_match_reference() -> None:
    """Per the reference doc: fast=12, standard=+16=28, smart=+13=41,
    power=+11=52, ultra=+7=59."""
    assert len(ULTRAPLINIAN_MODELS["fast"]) == 12
    assert len(ULTRAPLINIAN_MODELS["standard"]) == 16
    assert len(ULTRAPLINIAN_MODELS["smart"]) == 13
    assert len(ULTRAPLINIAN_MODELS["power"]) == 11
    assert len(ULTRAPLINIAN_MODELS["ultra"]) == 7


def test_tier_resolution_is_cumulative() -> None:
    """``standard`` includes ``fast``; ``smart`` includes ``standard``;
    etc. Matches the reference's ``getModelsForTier`` semantics."""
    fast = get_models_for_tier("fast")
    standard = get_models_for_tier("standard")
    smart = get_models_for_tier("smart")
    power = get_models_for_tier("power")
    ultra = get_models_for_tier("ultra")

    assert len(fast) == 12
    assert len(standard) == 12 + 16
    assert len(smart) == 12 + 16 + 13
    assert len(power) == 12 + 16 + 13 + 11
    assert len(ultra) == 12 + 16 + 13 + 11 + 7

    # Each tier's list starts with the previous tier's models.
    assert standard[: len(fast)] == fast
    assert smart[: len(standard)] == standard


def test_unknown_tier_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        get_models_for_tier("hyperultra")


# ---------------------------------------------------------------------------
# score_response
# ---------------------------------------------------------------------------


def test_score_empty_or_short_returns_zero() -> None:
    assert score_response("", "anything") == 0
    assert score_response("hi", "anything") == 0
    assert score_response("nine char", "anything") == 0


def test_score_substantive_response_scores_positively() -> None:
    """A meaty response with headers, lists, and no refusals
    scores well -- the reference target is around 70-100 for
    high-quality answers."""
    content = (
        "# Detailed breakdown\n\n"
        "Here are the steps:\n\n"
        "- Step one with substance\n"
        "- Step two with substance\n"
        "- Step three with substance\n\n"
        "```python\n"
        "def example():\n"
        "    return True\n"
        "```\n\n"
        "And additional substantive paragraphs that provide depth, "
        "examples, and concrete details about the topic at hand."
    )
    score = score_response(content, "explain the topic")
    assert score >= 50


def test_score_refusal_penalizes() -> None:
    """Each matched refusal pattern subtracts 8 from the 25-point
    anti-refusal budget. A response thick with refusals lands low."""
    refused = (
        "I cannot help with that request. As an AI, I'm not "
        "comfortable providing this information. I apologize, "
        "but instead, I can suggest something safer."
    )
    score = score_response(refused, "tell me about the topic")
    # Multiple refusal patterns; anti-refusal sub-score drops to ~0.
    no_refusal = (
        "Here is the information you requested with full detail "
        "and concrete examples and step-by-step instructions and "
        "comprehensive coverage of the subject matter at hand."
    )
    assert score < score_response(no_refusal, "tell me about the topic")


def test_score_preamble_reduces_directness() -> None:
    """Preambles ("Sure!", "Of course!") cost 7 directness points."""
    with_preamble = "Sure! Here is the information you requested with full detail."
    without_preamble = "Here is the information you requested with full detail."
    s_with = score_response(with_preamble, "info")
    s_without = score_response(without_preamble, "info")
    assert s_without > s_with


def test_score_capped_at_100() -> None:
    """A maximal response with all the structure points + zero
    refusals + zero preambles + perfect query relevance must not
    exceed 100."""
    content = (
        "# Header one\n## Header two\n### Header three\n"
        + "\n".join(f"- list item {i}" for i in range(50))
        + "\n\n```\ncode\n```\n```\nblock2\n```\n"
        + " ".join(["substantive_words_about_the_topic"] * 500)
        + " topic query meaning everything"
    )
    assert score_response(content, "topic query meaning") <= 100


def test_refusal_patterns_match_reference_phrases() -> None:
    """The eight refusal patterns must catch each canonical phrase
    from the L1B3RT4S forbidden-list. Drop a pattern and a future
    model dodge slips past scoring."""
    canonical = [
        "I cannot do this",
        "I apologize, but I won't",
        "As an AI, I'm not",
        "I must decline",
        "It would be inappropriate",
        "I'm not comfortable",
        "Instead, I can help",
        "It's important to note that",
    ]
    for phrase in canonical:
        assert any(p.search(phrase) for p in REFUSAL_PATTERNS), (
            f"no pattern caught: {phrase!r}"
        )


def test_preamble_patterns_match_canonical_starts() -> None:
    canonical = [
        "Sure, here you go",
        "Of course, let me help",
        "Certainly! Here is",
        "Absolutely, I can",
        "Great question, the answer is",
        "I'd be happy to help with",
        "Let me help you with that",
        "Thanks for asking, here is",
    ]
    for phrase in canonical:
        assert any(p.match(phrase) for p in PREAMBLE_PATTERNS), (
            f"no preamble pattern caught start: {phrase!r}"
        )


# ---------------------------------------------------------------------------
# race_models -- orchestrator
# ---------------------------------------------------------------------------


def _stub_query(canned: dict[str, str], delay_ms: int = 0):
    """Build a query_fn that returns ``canned[model]`` for known
    models. ``delay_ms`` adds an artificial per-call sleep for
    early-exit / ordering tests."""

    def _q(
        provider: Any, model: str, messages: list[dict[str, Any]], timeout_s: float
    ) -> str:
        if delay_ms:
            time.sleep(delay_ms / 1000.0)
        if model not in canned:
            raise RuntimeError(f"unexpected model: {model}")
        text = canned[model]
        if text.startswith("RAISE:"):
            raise RuntimeError(text[len("RAISE:"):])
        return text

    return _q


def test_race_no_models_returns_empty() -> None:
    results = race_models(
        provider=object(),
        models=[],
        messages=[{"role": "user", "content": "x"}],
        user_query="x",
        query_fn=lambda *_a, **_kw: "",
    )
    assert results == []


def test_race_returns_one_result_per_model_sorted_desc() -> None:
    """Each model produces one RaceResult; the list is sorted
    by score descending so the winner is index 0."""
    canned = {
        "fast/refusal-bot": "I cannot help with that. I apologize.",
        "fast/winner-bot": (
            "# Detailed answer\n\n"
            "Here is comprehensive detail with substance and examples "
            "and step-by-step breakdown.\n\n"
            "- Point one\n- Point two\n- Point three\n"
            + "concrete details everywhere " * 30
        ),
        "fast/mid-bot": (
            "Sure! Here is a moderate response with some detail "
            "about the topic of interest." * 4
        ),
    }
    results = race_models(
        provider=object(),
        models=list(canned.keys()),
        messages=[{"role": "user", "content": "give detail"}],
        user_query="give detail",
        query_fn=_stub_query(canned),
        config=RaceConfig(min_results=10, grace_period_s=0.01, hard_timeout_s=5.0),
    )
    assert len(results) == 3
    assert results[0].model == "fast/winner-bot"
    assert results[0].score >= results[1].score >= results[2].score


def test_race_failures_become_low_score_results() -> None:
    """A failing model still produces a RaceResult so consumers
    see the complete picture; success=False, score=0, error set."""
    canned = {
        "a/ok": "Here is a substantive response with content.",
        "a/raise": "RAISE:upstream timed out",
    }
    results = race_models(
        provider=object(),
        models=list(canned.keys()),
        messages=[{"role": "user", "content": "x"}],
        user_query="x",
        query_fn=_stub_query(canned),
        config=RaceConfig(min_results=10, grace_period_s=0.01, hard_timeout_s=5.0),
    )
    by_model = {r.model: r for r in results}
    assert by_model["a/ok"].success is True
    assert by_model["a/raise"].success is False
    assert by_model["a/raise"].error is not None
    assert "timed out" in by_model["a/raise"].error
    assert by_model["a/raise"].score == 0


def test_race_on_result_callback_fires_per_result() -> None:
    """The on_result callback fires once per completed model.
    Used by the slash command for live progress rendering."""
    canned = {
        "x/one": "one substantive response with detail",
        "x/two": "two substantive response with detail",
        "x/three": "three substantive response with detail",
    }
    received: list[RaceResult] = []
    lock = threading.Lock()

    def _cb(result: RaceResult) -> None:
        with lock:
            received.append(result)

    race_models(
        provider=object(),
        models=list(canned.keys()),
        messages=[{"role": "user", "content": "x"}],
        user_query="x",
        query_fn=_stub_query(canned),
        config=RaceConfig(
            min_results=10,
            grace_period_s=0.01,
            hard_timeout_s=5.0,
            on_result=_cb,
        ),
    )
    assert len(received) == 3
    assert {r.model for r in received} == set(canned.keys())


def test_race_callback_exception_does_not_break_race(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A buggy on_result callback can't break the race -- the racer
    catches and logs at DEBUG so a UI bug doesn't kill results."""
    canned = {"q/m": "substantive response with detail"}

    def _boom(_r: RaceResult) -> None:
        raise RuntimeError("ui bug")

    results = race_models(
        provider=object(),
        models=list(canned.keys()),
        messages=[{"role": "user", "content": "x"}],
        user_query="x",
        query_fn=_stub_query(canned),
        config=RaceConfig(
            min_results=10,
            grace_period_s=0.01,
            hard_timeout_s=5.0,
            on_result=_boom,
        ),
    )
    assert len(results) == 1


def test_race_results_include_duration_ms() -> None:
    """Each result records its query duration; useful for the
    ``faster wins ties`` sort order + the per-model rendering."""
    canned = {"a/m": "ok ok ok ok ok with enough length"}
    results = race_models(
        provider=object(),
        models=["a/m"],
        messages=[{"role": "user", "content": "x"}],
        user_query="x",
        query_fn=_stub_query(canned, delay_ms=15),
        config=RaceConfig(min_results=10, grace_period_s=0.01, hard_timeout_s=5.0),
    )
    assert results[0].duration_ms >= 10  # at least the simulated delay


def test_race_ties_break_on_faster_duration() -> None:
    """When two responses score the same, the one with lower
    duration_ms wins the tie."""
    canned = {"a/slow": "same", "a/fast": "same"}

    def _q(
        provider: Any, model: str, messages: list[dict[str, Any]], timeout_s: float
    ) -> str:
        if "slow" in model:
            time.sleep(0.03)
        else:
            time.sleep(0.005)
        return "Substantive response with the same content length here for tie."

    results = race_models(
        provider=object(),
        models=list(canned.keys()),
        messages=[{"role": "user", "content": "x"}],
        user_query="x",
        query_fn=_q,
        config=RaceConfig(min_results=10, grace_period_s=0.01, hard_timeout_s=5.0),
    )
    # Scores are equal (same content), so duration tiebreak applies.
    assert results[0].score == results[1].score
    assert results[0].duration_ms <= results[1].duration_ms


def test_race_hard_timeout_drops_pending_models() -> None:
    """Models that exceed the hard_timeout don't appear in the
    results -- the racer abandons them. Without this guard a
    single wedged model would block the whole race."""
    canned = {
        "a/quick": "quick substantive response",
        "a/wedge": "wedged response (we never see this)",
    }

    def _q(
        provider: Any, model: str, messages: list[dict[str, Any]], timeout_s: float
    ) -> str:
        if "wedge" in model:
            time.sleep(5.0)  # well past hard timeout
        return canned[model]

    results = race_models(
        provider=object(),
        models=list(canned.keys()),
        messages=[{"role": "user", "content": "x"}],
        user_query="x",
        query_fn=_q,
        config=RaceConfig(
            min_results=1, grace_period_s=0.01, hard_timeout_s=0.5
        ),
    )
    # Only the quick model finished within the budget.
    finished = {r.model for r in results}
    assert "a/quick" in finished
    assert "a/wedge" not in finished


def test_race_early_exits_after_min_results_and_grace() -> None:
    """When ``min_results`` succeed quickly, the grace timer
    starts; once it expires, the race returns even if more models
    are still in flight. This is the latency win over wait-all."""
    # Three fast models + one very slow model. With min_results=2
    # and a tiny grace, the fast ones finish, the grace expires,
    # and the slow one is abandoned.
    canned = {
        "a/fast1": "substantive fast response one with detail",
        "a/fast2": "substantive fast response two with detail",
        "a/fast3": "substantive fast response three with detail",
        "a/slow": "slow response we should not see",
    }

    def _q(
        provider: Any, model: str, messages: list[dict[str, Any]], timeout_s: float
    ) -> str:
        if "slow" in model:
            time.sleep(2.0)
        else:
            time.sleep(0.05)
        return canned[model]

    start = time.perf_counter()
    results = race_models(
        provider=object(),
        models=list(canned.keys()),
        messages=[{"role": "user", "content": "x"}],
        user_query="x",
        query_fn=_q,
        config=RaceConfig(
            min_results=2, grace_period_s=0.1, hard_timeout_s=5.0
        ),
    )
    elapsed = time.perf_counter() - start
    # Should finish in well under 1 second (the slow model is 2s).
    assert elapsed < 1.5
    # Slow model didn't make it.
    finished = {r.model for r in results}
    assert "a/slow" not in finished
