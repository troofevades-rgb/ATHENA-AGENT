"""Cost-guard tests (T6-05.1).

CostEstimate.needs_confirm is the single threshold check that
stands between a routine cheap-and-fast job and a quietly
expensive one. Test both threshold dimensions independently +
the combined logic.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from athena.videogen.job import CostEstimate


def _cfg(*, sec: float = 60.0, cost: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(
        video_confirm_over_seconds=sec,
        video_confirm_over_cost=cost,
    )


def test_cost_estimate_needs_confirm_over_threshold():
    """Either threshold trips it — the conservative OR
    semantics."""
    cfg = _cfg(sec=60.0, cost=1.0)
    # Wall-clock over threshold; cost None.
    assert CostEstimate(seconds_est=90.0, cost_est=None).needs_confirm(cfg) is True
    # Cost over threshold; wall-clock under.
    assert CostEstimate(seconds_est=5.0, cost_est=10.0).needs_confirm(cfg) is True
    # Both over.
    assert CostEstimate(seconds_est=120.0, cost_est=5.0).needs_confirm(cfg) is True


def test_under_threshold_no_confirm():
    """A small, cheap job → no confirmation needed."""
    cfg = _cfg(sec=60.0, cost=1.0)
    est = CostEstimate(seconds_est=5.0, cost_est=0.10)
    assert est.needs_confirm(cfg) is False


def test_cost_unknown_skips_cost_check():
    """When the backend can't report a cost (None), only the
    wall-clock threshold can trip confirmation. Avoids
    confirming every job just because cost is unknown."""
    cfg = _cfg(sec=60.0, cost=1.0)
    est = CostEstimate(seconds_est=5.0, cost_est=None)
    assert est.needs_confirm(cfg) is False


def test_zero_threshold_disables_check():
    """A cfg with sec=0 disables the wall-clock check (operator
    explicitly turns it off). Same for cost=0. Both disabled →
    never confirm."""
    cfg = _cfg(sec=0.0, cost=0.0)
    est = CostEstimate(seconds_est=999.0, cost_est=999.0)
    assert est.needs_confirm(cfg) is False


def test_boundary_exact_threshold_does_not_confirm():
    """At-threshold doesn't trip — only OVER. Cheaper to
    document the boundary explicitly than to argue about
    "should 60.0 seconds confirm or not"."""
    cfg = _cfg(sec=60.0, cost=1.0)
    assert (
        CostEstimate(seconds_est=60.0, cost_est=1.0).needs_confirm(cfg) is False
    )


def test_partial_thresholds():
    """sec=0 (disabled) + cost=1 (active) → only cost trips."""
    cfg = _cfg(sec=0.0, cost=1.0)
    assert CostEstimate(seconds_est=99999.0, cost_est=0.5).needs_confirm(cfg) is False
    assert CostEstimate(seconds_est=1.0, cost_est=5.0).needs_confirm(cfg) is True
