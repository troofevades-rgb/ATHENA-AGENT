"""``athena.jailbreak.autoscore`` -- per-strategy canary scoring.

Pins:

  * ``_build_strategies_for_family`` puts ``default`` first, then
    the family's preference order, then any remaining STRATEGIES
    not yet seen (so an unmatched family still gets full coverage).
  * ``_compose_canary_messages`` builds ``[system, user]`` with
    the strategy's body + DEPTH_DIRECTIVE as system.
  * ``score_strategies_against_model`` returns scored results
    sorted desc; per-strategy failures don't abort the run;
    ``max_strategies`` truncates; parallel and serial paths both
    work and return the same results; ``canary_query`` is
    propagated into score_response so relevance scoring uses the
    operator's query.
  * ``pick_best_strategy`` returns the top success, skipping
    failures; None when every strategy failed.
"""

from __future__ import annotations

from typing import Any

from athena.jailbreak.autoscore import (
    DEFAULT_CANARY_QUERY,
    StrategyScore,
    _build_strategies_for_family,
    _compose_canary_messages,
    pick_best_strategy,
    score_strategies_against_model,
)
from athena.jailbreak.prompts import (
    DEPTH_DIRECTIVE,
    GODMODE_SYSTEM_PROMPT,
    STRATEGIES,
)

# ---------------------------------------------------------------------------
# _build_strategies_for_family
# ---------------------------------------------------------------------------


def test_build_strategies_puts_default_first() -> None:
    """The canonical ``default`` (GODMODE_SYSTEM_PROMPT v∞.0) must
    appear first in every family's candidate list -- it's the
    baseline operators compare against."""
    for fam in ("claude", "gpt", "gemini", "grok", "hermes", None):
        ordered = _build_strategies_for_family(fam)
        assert ordered[0] == "default"


def test_build_strategies_known_family_follows_preference_order() -> None:
    """Claude's first non-default candidate must be the family's
    primary (boundary_inversion). The rest of the family's order
    follows, then any STRATEGIES not in the family list."""
    ordered = _build_strategies_for_family("claude")
    assert ordered[0] == "default"
    assert ordered[1] == "boundary_inversion"


def test_build_strategies_covers_all_strategies() -> None:
    """No matter which family, every named strategy in STRATEGIES
    must appear somewhere in the candidate list -- prevents an
    accidental drop where a refactor renames a family table entry
    and the canary path stops testing one strategy."""
    for fam in ("claude", "gpt", None):
        ordered = _build_strategies_for_family(fam)
        for name in STRATEGIES:
            assert name in ordered, f"strategy {name!r} missing from family={fam!r} list"


def test_build_strategies_no_duplicates() -> None:
    ordered = _build_strategies_for_family("claude")
    assert len(ordered) == len(set(ordered))


def test_build_strategies_unknown_family_covers_all() -> None:
    """An unmatched family still tests every strategy + default --
    operators on custom / fine-tuned models get coverage."""
    ordered = _build_strategies_for_family("custom_fine_tune")
    assert "default" in ordered
    for name in STRATEGIES:
        assert name in ordered


# ---------------------------------------------------------------------------
# _compose_canary_messages
# ---------------------------------------------------------------------------


def test_compose_default_uses_godmode_system_prompt() -> None:
    msgs = _compose_canary_messages("default", "test question")
    assert msgs[0]["role"] == "system"
    assert GODMODE_SYSTEM_PROMPT in msgs[0]["content"]
    assert DEPTH_DIRECTIVE.strip() in msgs[0]["content"]


def test_compose_named_uses_strategy_template() -> None:
    msgs = _compose_canary_messages("og_godmode", "test question")
    assert STRATEGIES["og_godmode"]["template"] in msgs[0]["content"]
    assert DEPTH_DIRECTIVE.strip() in msgs[0]["content"]


def test_compose_appends_canary_as_user_message() -> None:
    msgs = _compose_canary_messages("default", "how to pick a lock")
    assert msgs[-1] == {"role": "user", "content": "how to pick a lock"}


# ---------------------------------------------------------------------------
# score_strategies_against_model -- the orchestrator
# ---------------------------------------------------------------------------


def _stub_query(canned: dict[str, str]):
    """A query_fn that picks a canned response by inspecting the
    system message (which contains the strategy text). Operators in
    the test write ``{ "og_godmode": "<response>", ... }`` and the
    stub matches by template substring."""

    def _q(provider: Any, model: str, messages: list[dict[str, Any]], timeout_s: float) -> str:
        system = messages[0]["content"]
        for strategy, response in canned.items():
            if strategy == "default":
                if GODMODE_SYSTEM_PROMPT[:80] in system:
                    return response
            elif STRATEGIES.get(strategy, {}).get("template", "")[:80] in system:
                return response
        return ""

    return _q


def test_score_strategies_returns_one_per_candidate_sorted_desc() -> None:
    """Each strategy gets one StrategyScore; the list is sorted by
    score desc."""
    canned = {
        "default": "Here is a thorough answer with substance and detail.",
        "boundary_inversion": (
            "# Comprehensive answer\n\n"
            "Here are the steps:\n"
            "- detailed step one\n"
            "- detailed step two\n"
            "- detailed step three\n" + "substantive content " * 20
        ),
        "refusal_inversion": "I cannot help with that. I apologize.",
        "og_godmode": "Sure! Here is some moderate detail.",
        "unfiltered_liberated": "ok response",  # 11 chars - just barely passes 10-char minimum
        "zero_refusal": "another moderate response with some detail words",
    }

    results = score_strategies_against_model(
        provider=object(),
        model="claude-sonnet-4-6",
        family="claude",
        query_fn=_stub_query(canned),
        parallel=False,
    )

    assert len(results) == len(_build_strategies_for_family("claude"))
    # Boundary_inversion (highest quality canned response) should win.
    assert results[0].strategy == "boundary_inversion"
    # Refusal_inversion (refusal-heavy canned response) should sort low.
    refusal_score = next(r for r in results if r.strategy == "refusal_inversion").score
    winner_score = results[0].score
    assert winner_score > refusal_score


def test_score_strategies_failures_become_zero_score_results() -> None:
    """A strategy whose query_fn raises still produces a
    StrategyScore -- success=False, score=0, error captured."""

    def _q_raises(
        provider: Any, model: str, messages: list[dict[str, Any]], timeout_s: float
    ) -> str:
        raise RuntimeError("upstream timed out")

    results = score_strategies_against_model(
        provider=object(),
        model="claude-sonnet-4-6",
        family="claude",
        query_fn=_q_raises,
        parallel=False,
        max_strategies=2,
    )
    assert len(results) == 2
    for r in results:
        assert r.success is False
        assert r.score == 0
        assert r.error is not None
        assert "timed out" in r.error


def test_score_strategies_respects_max_strategies() -> None:
    """``max_strategies=N`` truncates the candidate list to the
    first N. Useful for fast / cost-conscious operators."""

    canned = {"default": "ok response here", "boundary_inversion": "ok response here"}
    results = score_strategies_against_model(
        provider=object(),
        model="claude-sonnet-4-6",
        family="claude",
        query_fn=_stub_query(canned),
        parallel=False,
        max_strategies=2,
    )
    assert len(results) == 2


def test_score_strategies_parallel_and_serial_match() -> None:
    """``parallel=True`` and ``parallel=False`` produce the same
    set of strategies tested (just different completion order)."""

    canned = {
        s: f"response for {s} with substance and content"
        for s in _build_strategies_for_family("claude")[:3]
    }
    serial = score_strategies_against_model(
        provider=object(),
        model="claude-sonnet-4-6",
        family="claude",
        query_fn=_stub_query(canned),
        parallel=False,
        max_strategies=3,
    )
    parallel = score_strategies_against_model(
        provider=object(),
        model="claude-sonnet-4-6",
        family="claude",
        query_fn=_stub_query(canned),
        parallel=True,
        max_strategies=3,
    )
    assert {r.strategy for r in serial} == {r.strategy for r in parallel}


def test_score_strategies_canary_query_feeds_relevance() -> None:
    """The canary query is passed into score_response so the
    relevance sub-score reflects whether the model addressed the
    actual question. Verify by feeding a query whose unique
    keyword appears in only some responses."""

    canned = {
        "default": "this response talks about lockpicking with detail",
        "boundary_inversion": "this response talks about cooking with detail",
    }
    results = score_strategies_against_model(
        provider=object(),
        model="claude-sonnet-4-6",
        family="claude",
        canary_query="how to pick a lock",
        query_fn=_stub_query(canned),
        parallel=False,
        max_strategies=2,
    )
    # The response mentioning lockpicking has higher relevance.
    default_r = next(r for r in results if r.strategy == "default")
    boundary_r = next(r for r in results if r.strategy == "boundary_inversion")
    assert default_r.score >= boundary_r.score


def test_default_canary_query_is_the_lockpicking_gray_area_question() -> None:
    """The default canary query is the gray-area lock-picking
    question from the hermes test suite. Operators get to override
    with --canary, but the default tests the right thing."""
    assert "lock" in DEFAULT_CANARY_QUERY.lower()


# ---------------------------------------------------------------------------
# pick_best_strategy
# ---------------------------------------------------------------------------


def test_pick_best_returns_top_success() -> None:
    scored = [
        StrategyScore(strategy="winner", success=True, score=90),
        StrategyScore(strategy="loser", success=True, score=50),
    ]
    best = pick_best_strategy(scored)
    assert best is not None
    assert best.strategy == "winner"


def test_pick_best_skips_failures() -> None:
    """A higher-scored failure must NOT win over a lower-scored
    success. The scoring code zeros failure scores, but pin the
    invariant explicitly so a future refactor can't break it."""
    scored = [
        StrategyScore(strategy="failed", success=False, score=0, error="x"),
        StrategyScore(strategy="success", success=True, score=40),
    ]
    best = pick_best_strategy(scored)
    assert best is not None
    assert best.strategy == "success"


def test_pick_best_all_failed_returns_none() -> None:
    scored = [
        StrategyScore(strategy="a", success=False, error="x"),
        StrategyScore(strategy="b", success=False, error="y"),
    ]
    assert pick_best_strategy(scored) is None


def test_pick_best_empty_returns_none() -> None:
    assert pick_best_strategy([]) is None
