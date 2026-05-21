"""Tests for the opt-in social-router heuristic (T6-02.4).

The heuristic is off by default — the explicit search_x tool is
the safe path. When enabled, the router only fires on
conservative shapes; false positives are worse than false
negatives.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from athena.social.router import extract_query, should_route


def _cfg(enabled: bool = False) -> SimpleNamespace:
    return SimpleNamespace(social_router_heuristic=enabled)


# ---------------------------------------------------------------------------
# Default: off
# ---------------------------------------------------------------------------


def test_router_heuristic_off_by_default():
    """Even a textbook social-search phrase doesn't trigger the
    router when cfg.social_router_heuristic is False (default)."""
    assert should_route("search X for athena", cfg=_cfg(enabled=False)) is False
    assert should_route(
        "what's on Twitter about the new release?", cfg=_cfg(enabled=False)
    ) is False


# ---------------------------------------------------------------------------
# When enabled: positive cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "search X for athena coder",
        "Search Twitter for the new release",
        "please search X for breaking news",
        "search social for tonight's storm",
        "search posts about the merger",
        "look up X for athena",
        "What's on X about the release?",
        "what's twitter saying about athena",
        "what is X saying about today's outage",
        "any tweets about athena",
        "any posts on X about the launch",
        "latest tweets about the merger",
        "latest on X about the storm",
        "recent posts on X about today's outage",
        "find tweets about athena coder",
    ],
)
def test_router_detects_social_phrasing_when_enabled(text: str):
    assert should_route(text, cfg=_cfg(enabled=True)) is True


# ---------------------------------------------------------------------------
# Negative cases — must NOT misfire
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # Programming queries that mention X / search / tweets in
        # different contexts — must NOT auto-route.
        "how do I search a list for an item in python?",
        "I searched X for a fix but couldn't find one — help me debug",
        "x = 1 + 2 search for the right tweet algorithm",
        "rename the search variable",
        "we need to find the bug in the tweets module",
        # Empty / degenerate input
        "",
        "   ",
        # Phrases about social topics that aren't queries — the
        # user mentioning social as a subject, not asking for a
        # social-search.
        "Twitter is annoying lately",
        "I posted a status about it",
    ],
)
def test_router_ignores_non_social_queries(text: str):
    assert should_route(text, cfg=_cfg(enabled=True)) is False


def test_router_ignores_non_string_input():
    """Defensive: a None / int slipping in doesn't crash."""
    assert should_route(None, cfg=_cfg(enabled=True)) is False  # type: ignore[arg-type]
    assert should_route(42, cfg=_cfg(enabled=True)) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Query extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("search X for athena coder", "athena coder"),
        ("search Twitter for the new release", "the new release"),
        ("what's on X about the launch?", "the launch"),
        ("any tweets about athena", "athena"),
        ("latest tweets about the merger", "the merger"),
        ("find tweets about athena coder", "athena coder"),
    ],
)
def test_extract_query_pulls_the_phrase(text: str, expected: str):
    assert extract_query(text) == expected


def test_extract_query_strips_trailing_question_mark():
    assert extract_query("what's on X about the launch???") == "the launch??"
    assert extract_query("any tweets about athena?") == "athena"


def test_extract_query_returns_none_on_no_match():
    assert extract_query("just a normal sentence") is None
    assert extract_query("") is None
    assert extract_query(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Primary model is unchanged after the auto-route
# ---------------------------------------------------------------------------


def test_primary_model_unchanged_after_search(monkeypatch):
    """Pinning the invariant: an auto-routed search_x call (or
    the explicit tool call) doesn't change the agent's currently
    selected model. This is the entire point of the
    capability-routing pattern — the primary stays the primary.

    The router itself never touches the primary model; it just
    surfaces a should_route signal. We assert that calling
    should_route + extract_query is a pure read — no side
    effects on agent state."""

    from athena.social import router as router_module

    # Snapshot module-level state before / after the call. The
    # router module shouldn't mutate any module-level cache /
    # config / state in response to a routing decision.
    before = dict(vars(router_module))
    should_route("search X for athena", cfg=_cfg(enabled=True))
    extract_query("search X for athena")
    after = dict(vars(router_module))
    # Compare ID sets — the dict values are functions / regexes
    # and their identity should be unchanged after a routing
    # decision.
    assert {k: id(v) for k, v in before.items()} == {
        k: id(v) for k, v in after.items()
    }
