"""Tests for athena.verify.outcome (T5-04.1)."""

from __future__ import annotations

from athena.verify.outcome import VerificationOutcome

# ---------------------------------------------------------------------------
# Passed property
# ---------------------------------------------------------------------------


def test_passed_when_outcome_passed() -> None:
    o = VerificationOutcome(path="a.py", outcome="passed")
    assert o.passed is True
    assert o.failed is False


def test_passed_when_outcome_skipped() -> None:
    """A skipped verification (loop disabled / per-leg degradation)
    still counts as "didn't block" — the write went through."""
    o = VerificationOutcome(path="a.py", outcome="skipped")
    assert o.passed is True


def test_passed_false_for_failed_diagnostics() -> None:
    o = VerificationOutcome(
        path="a.py",
        outcome="failed_diagnostics",
        introduced_errors=["e"],
    )
    assert o.passed is False
    assert o.failed is True


def test_passed_false_for_failed_run() -> None:
    o = VerificationOutcome(path="a.py", outcome="failed_run", run_exit_code=1)
    assert o.passed is False


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def test_report_clean_on_pass() -> None:
    o = VerificationOutcome(path="athena/foo.py", outcome="passed")
    out = o.report()
    assert out.startswith("✓")
    assert "athena/foo.py" in out
    assert "Roll back" not in out


def test_report_skipped_marker() -> None:
    o = VerificationOutcome(path="x.py", outcome="skipped")
    out = o.report()
    assert "skipped" in out.lower()


def test_report_lists_introduced_errors() -> None:
    o = VerificationOutcome(
        path="x.py",
        outcome="failed_diagnostics",
        introduced_errors=[
            "Cannot find name 'foo'",
            "Type mismatch on line 10",
        ],
        checkpoint_id="cp-abc",
    )
    out = o.report()
    assert out.startswith("✗")
    assert "2 error(s)" in out
    assert "Cannot find name 'foo'" in out
    assert "Type mismatch on line 10" in out


def test_report_offers_rollback_on_failure_with_checkpoint() -> None:
    o = VerificationOutcome(
        path="x.py",
        outcome="failed_diagnostics",
        introduced_errors=["bug"],
        checkpoint_id="cp-XYZ",
    )
    out = o.report()
    assert "Roll back with: /rollback-to cp-XYZ" in out


def test_report_no_rollback_offer_when_no_checkpoint() -> None:
    """T3-03 absent → no checkpoint_id → no rollback line."""
    o = VerificationOutcome(
        path="x.py",
        outcome="failed_diagnostics",
        introduced_errors=["bug"],
        checkpoint_id=None,
    )
    out = o.report()
    assert "Roll back" not in out


def test_report_after_auto_rollback_says_so() -> None:
    """When verify_auto_rollback fired, the report tells the user
    the revert already happened — no "/rollback-to" prompt."""
    o = VerificationOutcome(
        path="x.py",
        outcome="failed_diagnostics",
        introduced_errors=["bug"],
        checkpoint_id="cp-1",
        rolled_back=True,
    )
    out = o.report()
    assert "Roll back with: /rollback-to" not in out
    assert "auto-rolled back" in out.lower()


def test_report_failed_run_includes_exit_and_stderr() -> None:
    o = VerificationOutcome(
        path="x.py",
        outcome="failed_run",
        run_exit_code=2,
        run_stderr_tail="ModuleNotFoundError: pytest\nfail",
        checkpoint_id="cp-1",
    )
    out = o.report()
    assert "exit 2" in out
    assert "ModuleNotFoundError" in out
    assert "Roll back with: /rollback-to cp-1" in out


def test_report_failed_run_handles_missing_stderr() -> None:
    o = VerificationOutcome(path="x.py", outcome="failed_run", run_exit_code=1)
    out = o.report()
    assert "(no stderr captured)" in out


def test_report_truncates_long_error_list() -> None:
    """The report keeps the first 8 errors and adds an
    "... and N more" marker. Long lists drown the user otherwise."""
    o = VerificationOutcome(
        path="x.py",
        outcome="failed_diagnostics",
        introduced_errors=[f"err {i}" for i in range(20)],
    )
    out = o.report()
    assert "err 0" in out
    assert "err 7" in out  # 8 errors shown (0..7)
    assert "err 8" not in out
    assert "... and 12 more" in out


# ---------------------------------------------------------------------------
# to_dict (audit-log serialisation)
# ---------------------------------------------------------------------------


def test_to_dict_round_trip_shape() -> None:
    o = VerificationOutcome(
        path="x.py",
        outcome="failed_run",
        checkpoint_id="cp-1",
        run_exit_code=3,
        run_stderr_tail="oops",
        retries=1,
        rolled_back=False,
    )
    d = o.to_dict()
    assert d["path"] == "x.py"
    assert d["outcome"] == "failed_run"
    assert d["checkpoint_id"] == "cp-1"
    assert d["run_exit_code"] == 3
    assert d["run_stderr_tail"] == "oops"
    assert d["retries"] == 1
    assert d["rolled_back"] is False
    assert d["introduced_errors"] == []


# ---------------------------------------------------------------------------
# blocked_by_policy (sandbox runner refused the verify command)
# ---------------------------------------------------------------------------


def test_blocked_by_policy_counts_as_failed() -> None:
    """A run blocked by the shell/sandbox policy is a failure, not a pass —
    the write went in but couldn't be verified."""
    o = VerificationOutcome(
        path="a.py",
        outcome="blocked_by_policy",
        run_exit_code=-1,
        run_stderr_tail="verify command blocked by policy: rm -rf denied",
    )
    assert o.passed is False
    assert o.failed is True


def test_report_blocked_by_policy_shows_policy_message() -> None:
    o = VerificationOutcome(
        path="a.py",
        outcome="blocked_by_policy",
        checkpoint_id="cp-9",
        run_exit_code=-1,
        run_stderr_tail="verify command blocked by policy: operation not allowed",
    )
    rep = o.report()
    assert "blocked by policy" in rep
    assert "operation not allowed" in rep
    # Failure → still offers the rollback hint when a checkpoint exists.
    assert "/rollback-to cp-9" in rep


def test_to_dict_preserves_blocked_by_policy() -> None:
    d = VerificationOutcome(path="x.py", outcome="blocked_by_policy").to_dict()
    assert d["outcome"] == "blocked_by_policy"
