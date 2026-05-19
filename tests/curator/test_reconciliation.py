"""Tests for athena.curator.reconciliation.

The reconciler diffs a pre-fork skill snapshot against a post-fork one
to surface drift between what the curator's YAML CLAIMED and what
actually changed on disk. Three drift classes are tracked:

- ``missing_from_fs``: YAML said remove but it's still active.
- ``unexpected_archive``: archived on disk but YAML didn't say so.
- ``no_op_after_keep``: YAML said KEEP_AS_IS but state changed.
"""

from __future__ import annotations

from athena.curator.reconciliation import (
    DriftReport,
    SkillSnapshot,
    reconcile,
)


def _snap(name: str, *, state: str = "active", archived: bool = False) -> SkillSnapshot:
    return SkillSnapshot(
        name=name,
        state=state,
        is_archived=archived,
        skill_dir=f"/skills/{name}",
    )


def _yaml_run(
    skill: str,
    decision: str,
    target: str | None = None,
    absorbed_into: str | None = None,
) -> dict:
    return {
        "skill": skill,
        "decision": decision,
        "target": target,
        "absorbed_into": absorbed_into,
        "rationale": "test",
    }


# ---- clean cases --------------------------------------------------------


def test_clean_keep_no_op() -> None:
    before = {"a": _snap("a")}
    after = {"a": _snap("a")}
    runs = [_yaml_run("a", "KEEP_AS_IS")]
    drift = reconcile(before, after, runs)
    assert drift.is_clean


def test_clean_consolidation() -> None:
    """YAML said consolidate; disk shows archived. Clean."""
    before = {"a": _snap("a"), "umbrella": _snap("umbrella")}
    after = {
        "a": _snap("a", state="archived", archived=True),
        "umbrella": _snap("umbrella"),
    }
    runs = [_yaml_run("a", "CONSOLIDATE_INTO", "umbrella", "umbrella")]
    drift = reconcile(before, after, runs)
    assert drift.is_clean


def test_clean_create_umbrella() -> None:
    """CREATE_UMBRELLA names a new skill in `target`. Reconciler
    doesn't need to verify the new umbrella exists — the per-skill
    consolidation rows for absorbed siblings handle that."""
    before = {"old": _snap("old")}
    after = {
        "old": _snap("old", state="archived", archived=True),
        "new-umbrella": _snap("new-umbrella"),
    }
    runs = [
        _yaml_run("old", "CONSOLIDATE_INTO", "new-umbrella", "new-umbrella"),
        _yaml_run("new-umbrella", "CREATE_UMBRELLA", "new-umbrella"),
    ]
    drift = reconcile(before, after, runs)
    assert drift.is_clean


def test_clean_prune() -> None:
    before = {"stale": _snap("stale")}
    after = {"stale": _snap("stale", state="archived", archived=True)}
    runs = [_yaml_run("stale", "PRUNE")]
    drift = reconcile(before, after, runs)
    assert drift.is_clean


# ---- missing_from_fs ----------------------------------------------------


def test_consolidation_claim_but_skill_still_active() -> None:
    """YAML said CONSOLIDATE_INTO but the skill is still active on disk."""
    before = {"a": _snap("a"), "umbrella": _snap("umbrella")}
    after = {"a": _snap("a"), "umbrella": _snap("umbrella")}
    runs = [_yaml_run("a", "CONSOLIDATE_INTO", "umbrella", "umbrella")]
    drift = reconcile(before, after, runs)
    assert not drift.is_clean
    assert len(drift.missing_from_fs) == 1
    assert drift.missing_from_fs[0]["skill"] == "a"
    assert drift.missing_from_fs[0]["decision"] == "CONSOLIDATE_INTO"


def test_prune_claim_but_skill_still_active() -> None:
    before = {"x": _snap("x")}
    after = {"x": _snap("x")}
    runs = [_yaml_run("x", "PRUNE")]
    drift = reconcile(before, after, runs)
    assert len(drift.missing_from_fs) == 1


def test_each_demote_decision_tracked() -> None:
    """All three DEMOTE_TO_* decisions are removals — they must
    surface in missing_from_fs if disk says otherwise."""
    for decision in (
        "DEMOTE_TO_REFERENCES",
        "DEMOTE_TO_TEMPLATES",
        "DEMOTE_TO_SCRIPTS",
    ):
        before = {"x": _snap("x")}
        after = {"x": _snap("x")}  # still active
        runs = [_yaml_run("x", decision, "umbrella", "umbrella")]
        drift = reconcile(before, after, runs)
        assert len(drift.missing_from_fs) == 1, decision


# ---- unexpected_archive ------------------------------------------------


def test_archived_on_disk_but_not_in_yaml() -> None:
    """The fork archived something it didn't mention — surface it."""
    before = {"a": _snap("a"), "b": _snap("b")}
    after = {
        "a": _snap("a"),
        "b": _snap("b", state="archived", archived=True),
    }
    runs = [_yaml_run("a", "KEEP_AS_IS")]  # b not mentioned
    drift = reconcile(before, after, runs)
    assert len(drift.unexpected_archive) == 1
    assert drift.unexpected_archive[0]["skill"] == "b"


def test_archive_named_in_yaml_is_not_unexpected() -> None:
    before = {"a": _snap("a")}
    after = {"a": _snap("a", state="archived", archived=True)}
    runs = [_yaml_run("a", "PRUNE")]
    drift = reconcile(before, after, runs)
    assert drift.unexpected_archive == []


# ---- no_op_after_keep --------------------------------------------------


def test_keep_but_state_flipped() -> None:
    """Some other writer (or curator side-effect) flipped a kept skill."""
    before = {"a": _snap("a", state="active")}
    after = {"a": _snap("a", state="stale")}
    runs = [_yaml_run("a", "KEEP_AS_IS")]
    drift = reconcile(before, after, runs)
    assert len(drift.no_op_after_keep) == 1
    assert drift.no_op_after_keep[0]["before_state"] == "active"
    assert drift.no_op_after_keep[0]["after_state"] == "stale"


def test_keep_archive_status_flipped() -> None:
    before = {"a": _snap("a", state="active")}
    after = {"a": _snap("a", state="active", archived=True)}
    runs = [_yaml_run("a", "KEEP_AS_IS")]
    drift = reconcile(before, after, runs)
    assert len(drift.no_op_after_keep) == 1


# ---- to_dict --------------------------------------------------------


def test_to_dict_serializes_to_json_safe_structure() -> None:
    report = DriftReport(
        missing_from_fs=[{"skill": "a", "decision": "PRUNE", "observed_state": "active"}],
        unexpected_archive=[],
        no_op_after_keep=[],
    )
    data = report.to_dict()
    assert "missing_from_fs" in data
    assert data["missing_from_fs"][0]["skill"] == "a"
    assert data["unexpected_archive"] == []


def test_is_clean_true_for_empty_drift() -> None:
    assert DriftReport().is_clean


def test_is_clean_false_for_any_drift() -> None:
    assert not DriftReport(missing_from_fs=[{"x": "y"}]).is_clean
    assert not DriftReport(unexpected_archive=[{"x": "y"}]).is_clean
    assert not DriftReport(no_op_after_keep=[{"x": "y"}]).is_clean
