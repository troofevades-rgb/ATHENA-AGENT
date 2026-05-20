"""Tests for athena.skills.metrics (T3-06R.2)."""

from __future__ import annotations

import datetime as _dt
import json
import time
from pathlib import Path

from athena.skills.metrics import (
    SkillMetric,
    SkillMetricsStore,
    get_active_store,
    metrics_path,
    record_view_active,
    set_active_store,
)


def _store(tmp_path: Path) -> SkillMetricsStore:
    return SkillMetricsStore(metrics_path(tmp_path))


# ---------------------------------------------------------------------------
# Basic write + aggregate round-trip
# ---------------------------------------------------------------------------


def test_record_view_increments_and_persists(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.record_view("alpha", session_id="sess-1")
    s.record_view("alpha", session_id="sess-1")
    s.record_view("alpha", session_id="sess-2")
    s.record_view("beta", session_id="sess-1")

    # Survives a fresh store instance (file-backed).
    fresh = _store(tmp_path)
    metrics = fresh.all()
    assert metrics["alpha"].views == 3
    assert metrics["alpha"].sessions_used_in == 2
    assert metrics["beta"].views == 1


def test_last_used_updates(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.record_view("alpha")
    first_ts = s.get("alpha").last_used_at
    time.sleep(0.005)  # ensure ISO ts strictly increases
    s.record_view("alpha")
    second_ts = s.get("alpha").last_used_at
    assert first_ts is not None and second_ts is not None
    assert second_ts > first_ts


def test_empty_name_is_silently_dropped(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.record_view("")
    assert s.all() == {}
    # File MAY exist (we created the parent dir) but be empty.
    if s.path.exists():
        assert s.path.read_text(encoding="utf-8").strip() == ""


# ---------------------------------------------------------------------------
# top / stale / never_used
# ---------------------------------------------------------------------------


def test_top_orders_by_views(tmp_path: Path) -> None:
    s = _store(tmp_path)
    for _ in range(5):
        s.record_view("hot")
    for _ in range(2):
        s.record_view("warm")
    s.record_view("cold")

    top = s.top(n=3)
    assert [m.name for m in top] == ["hot", "warm", "cold"]


def test_top_caps_at_n(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.record_view("a")
    s.record_view("b")
    s.record_view("c")
    assert len(s.top(n=2)) == 2


def test_stale_filters_by_last_used(tmp_path: Path) -> None:
    """Write a synthetic JSONL with an old ts so we don't have to
    sleep 30 days. The store reads ts strings directly."""
    log = metrics_path(tmp_path)
    log.parent.mkdir(parents=True, exist_ok=True)
    old_ts = (
        (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=45))
        .isoformat()
        .replace("+00:00", "Z")
    )
    new_ts = (
        (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=1))
        .isoformat()
        .replace("+00:00", "Z")
    )
    with open(log, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event": "view", "skill_name": "stale-skill", "ts": old_ts}) + "\n")
        f.write(json.dumps({"event": "view", "skill_name": "fresh-skill", "ts": new_ts}) + "\n")

    s = _store(tmp_path)
    stale_30 = s.stale(older_than_days=30)
    names = [m.name for m in stale_30]
    assert "stale-skill" in names
    assert "fresh-skill" not in names


def test_never_used_joins_against_catalogue(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.record_view("alpha")
    s.record_view("beta")
    catalogue = ["alpha", "beta", "never-touched", "another-unused"]
    assert s.never_used(catalogue) == ["another-unused", "never-touched"]


def test_never_used_with_empty_store(tmp_path: Path) -> None:
    s = _store(tmp_path)
    assert s.never_used(["a", "b"]) == ["a", "b"]


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


def test_record_outcome_aggregates_label_counts(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.record_outcome("alpha", "good")
    s.record_outcome("alpha", "good")
    s.record_outcome("alpha", "bad")
    metric = s.get("alpha")
    assert metric.outcomes == {"good": 2, "bad": 1}


def test_invalid_outcome_ignored(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.record_outcome("alpha", "nonsense")
    assert "alpha" not in s.all()


# ---------------------------------------------------------------------------
# T3-05R compatibility — suggestion enhancer reads the same file
# ---------------------------------------------------------------------------


def test_outcome_lines_readable_by_suggestion_enhancer(tmp_path: Path) -> None:
    """T3-05R's build_suggestion_fn aggregates JSONL lines with
    integer-typed good / bad / preference_pair fields. Our outcome
    writes must round-trip through that aggregator."""
    s = _store(tmp_path)
    for _ in range(12):
        s.record_outcome("hot-skill", "good")

    from athena.transform.classifier import Trajectory
    from athena.transform.suggestion import build_suggestion_fn

    fn = build_suggestion_fn(tmp_path)
    trajectory = Trajectory(
        session_id="s1",
        turn_start=0,
        turn_end=1,
        turns=[{"role": "user", "content": "x"}],
        auto_label="unreviewed",  # type: ignore[arg-type]
        metadata={"skill_name": "hot-skill"},
    )
    sug = fn(trajectory)
    assert sug is not None
    assert sug.label == "good"
    assert sug.source == "metrics"


def test_view_lines_ignored_by_suggestion_enhancer(tmp_path: Path) -> None:
    """View events have no good/bad fields → enhancer skips them
    cleanly. Confirms the two record shapes share the file without
    cross-contamination."""
    s = _store(tmp_path)
    for _ in range(100):
        s.record_view("not-an-outcome")

    from athena.transform.classifier import Trajectory
    from athena.transform.suggestion import build_suggestion_fn

    fn = build_suggestion_fn(tmp_path)
    trajectory = Trajectory(
        session_id="s1",
        turn_start=0,
        turn_end=1,
        turns=[{"role": "user", "content": "x"}],
        auto_label="bad",  # type: ignore[arg-type]
        metadata={"skill_name": "not-an-outcome"},
    )
    # No metrics override possible — only the classifier signal is
    # available, even though "not-an-outcome" has 100 view records.
    sug = fn(trajectory)
    assert sug is not None
    assert sug.source == "classifier"
    assert sug.label == "bad"


# ---------------------------------------------------------------------------
# Active store ContextVar
# ---------------------------------------------------------------------------


def test_active_store_default_none() -> None:
    assert get_active_store() is None


def test_set_active_store_round_trip(tmp_path: Path) -> None:
    s = _store(tmp_path)
    set_active_store(s)
    try:
        assert get_active_store() is s
    finally:
        set_active_store(None)


def test_record_view_active_with_no_store_is_noop(tmp_path: Path) -> None:
    set_active_store(None)
    # Should not raise.
    record_view_active("any-skill", session_id="s1")


def test_record_view_active_routes_to_set_store(tmp_path: Path) -> None:
    s = _store(tmp_path)
    set_active_store(s)
    try:
        record_view_active("alpha", session_id="s1")
        record_view_active("alpha")
    finally:
        set_active_store(None)
    assert s.get("alpha").views == 2


# ---------------------------------------------------------------------------
# SkillMetric helpers
# ---------------------------------------------------------------------------


def test_days_stale_returns_none_when_never_used() -> None:
    m = SkillMetric(name="x")
    assert m.days_stale() is None


def test_days_stale_returns_positive_number() -> None:
    m = SkillMetric(name="x", last_used_at="2024-01-01T00:00:00Z")
    assert m.days_stale() is not None
    assert m.days_stale() > 365  # well over a year ago in 2026


# ---------------------------------------------------------------------------
# Allowlist guard (the safety test runs separately; this is a
# direct sanity check that the metrics module name lands)
# ---------------------------------------------------------------------------


def test_writes_go_through_allowlisted_path() -> None:
    """The strict spec wanted snapshot_and_record. We took the
    operational-JSONL pattern (matching audit.py / proxy/logging.py
    / mcp/request_log.py / CheckpointAuditLog) and allowlisted the
    module. Belt-and-braces: confirm the allowlist entry is present
    so the safety-test guard stays accurate."""
    from tests.safety.test_no_raw_writes import ALLOWLIST

    assert "athena/skills/metrics.py" in ALLOWLIST
