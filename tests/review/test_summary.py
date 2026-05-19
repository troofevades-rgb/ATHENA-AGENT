"""Tests for the review-summary extractor and user-facing formatter."""

from __future__ import annotations

from dataclasses import dataclass

from athena.agent.fork import ForkAction, ForkResult
from athena.review.summary import extract_summary, format_for_user


def _result_with(*actions: ForkAction) -> ForkResult:
    return ForkResult(final_response="done", actions=list(actions))


def test_extracts_memory_writes_from_fork_actions() -> None:
    r = _result_with(
        ForkAction(action="create", target="memory", name="user-role"),
        ForkAction(action="create", target="memory", name="merge-freeze"),
    )
    summary = extract_summary(r)
    assert [m["name"] for m in summary["memory_writes"]] == ["user-role", "merge-freeze"]
    assert summary["skill_changes"] == []


def test_extracts_skill_changes_from_fork_actions() -> None:
    r = _result_with(
        ForkAction(action="patch", target="skill", name="git-workflow"),
        ForkAction(action="create", target="skill", name="testing-patterns"),
    )
    summary = extract_summary(r)
    assert summary["memory_writes"] == []
    assert {s["name"] for s in summary["skill_changes"]} == {"git-workflow", "testing-patterns"}


def test_summary_empty_when_no_actions() -> None:
    r = _result_with()
    assert extract_summary(r) == {"memory_writes": [], "skill_changes": []}


def test_unknown_target_skipped() -> None:
    r = _result_with(ForkAction(action="x", target="unknown-thing", name="y"))
    summary = extract_summary(r)
    assert summary["memory_writes"] == [] and summary["skill_changes"] == []


def test_format_for_user_empty_summary() -> None:
    assert format_for_user({"memory_writes": [], "skill_changes": []}) == ""


def test_format_for_user_pluralizes_correctly() -> None:
    one = {
        "memory_writes": [{"name": "a", "action": "create", "detail": None}],
        "skill_changes": [],
    }
    assert format_for_user(one).startswith("Background review:")
    assert "1 memory entry" in format_for_user(one)

    two = {
        "memory_writes": [
            {"name": "a", "action": "create", "detail": None},
            {"name": "b", "action": "create", "detail": None},
        ],
        "skill_changes": [],
    }
    assert "2 memory entries" in format_for_user(two)


def test_format_for_user_combines_both_buckets() -> None:
    summary = {
        "memory_writes": [{"name": "a", "action": "create", "detail": None}],
        "skill_changes": [
            {"name": "g", "action": "patch", "detail": None},
            {"name": "h", "action": "patch", "detail": None},
        ],
    }
    out = format_for_user(summary)
    assert "memory" in out
    assert "skill" in out


def test_works_with_duck_typed_result() -> None:
    """Anything with .actions iterable of ForkAction-like objects is OK."""

    @dataclass
    class _R:
        actions: list

    r = _R(actions=[ForkAction(action="create", target="memory", name="x")])
    assert extract_summary(r) == {
        "memory_writes": [{"name": "x", "action": "create", "detail": None}],
        "skill_changes": [],
    }
