"""Verification outcome record + human-readable report (T5-04.1).

One :class:`VerificationOutcome` per `verify_write` call. Carries:

- ``outcome`` — one of ``"passed" | "failed_diagnostics" |
  "failed_run" | "skipped"``.
- ``checkpoint_id`` — the T3-03 checkpoint the loop captured
  before the write (None when T3-03 isn't available).
- ``introduced_errors`` — list of LSP error messages newly
  introduced by this write (failed_diagnostics path).
- ``run_exit_code`` + ``run_stderr_tail`` — exit-1 sandboxed-run
  details (failed_run path).
- ``retries`` — how many auto-retry attempts the wrapper used.
- ``rolled_back`` — True when ``verify_auto_rollback`` fired.

:meth:`report` is the user-facing rendering — leads with a
checkmark / cross, lists the specifics, and on failure tells the
user the exact ``/rollback-to <id>`` they can run.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Literal

# Tool-result return values use the same vocabulary so the model's
# `read_tool_result` flow can grep for them.
Outcome = Literal[
    "passed",
    "failed_diagnostics",
    "failed_run",
    "skipped",
]


_MAX_ERRORS_IN_REPORT = 8
_STDERR_TAIL_BYTES = 500


@dataclasses.dataclass
class VerificationOutcome:
    """Structured record of one verification cycle.

    All fields except ``path`` and ``outcome`` have sensible
    zero-defaults so the loop can populate just the bits relevant
    to the path it took.
    """

    path: str
    outcome: Outcome
    checkpoint_id: str | None = None
    introduced_errors: list[str] = dataclasses.field(default_factory=list)
    run_exit_code: int | None = None
    run_stderr_tail: str | None = None
    retries: int = 0
    rolled_back: bool = False

    @property
    def passed(self) -> bool:
        """Pure-success or skipped both count as "didn't block."
        Failures (failed_diagnostics / failed_run) are the only
        states the loop surfaces a rollback offer for."""
        return self.outcome in ("passed", "skipped")

    @property
    def failed(self) -> bool:
        return not self.passed

    def report(self) -> str:
        """Human-readable one-block summary. Trailing
        ``Roll back with: /rollback-to <id>`` line appears only on
        failure AND only when a checkpoint exists AND the loop
        hasn't already auto-rolled-back."""
        if self.outcome == "passed":
            return f"✓ verified {self.path}"
        if self.outcome == "skipped":
            return f"· verification skipped for {self.path}"

        if self.outcome == "failed_diagnostics":
            lines = "\n".join(f"  - {e}" for e in self.introduced_errors[:_MAX_ERRORS_IN_REPORT])
            extra = ""
            if len(self.introduced_errors) > _MAX_ERRORS_IN_REPORT:
                extra = f"\n  ... and {len(self.introduced_errors) - _MAX_ERRORS_IN_REPORT} more"
            head = (
                f"✗ {self.path}: write introduced "
                f"{len(self.introduced_errors)} error(s):\n{lines}{extra}"
            )
        else:  # failed_run
            tail = self.run_stderr_tail or "(no stderr captured)"
            head = f"✗ {self.path}: run failed (exit {self.run_exit_code}):\n  {tail}"

        if self.checkpoint_id and not self.rolled_back:
            head += f"\n  Roll back with: /rollback-to {self.checkpoint_id}"
        elif self.rolled_back:
            head += "\n  (auto-rolled back to pre-write checkpoint)"
        return head

    def to_dict(self) -> dict[str, Any]:
        """Audit-log-friendly serialisation."""
        return {
            "path": self.path,
            "outcome": self.outcome,
            "checkpoint_id": self.checkpoint_id,
            "introduced_errors": list(self.introduced_errors),
            "run_exit_code": self.run_exit_code,
            "run_stderr_tail": self.run_stderr_tail,
            "retries": self.retries,
            "rolled_back": self.rolled_back,
        }
