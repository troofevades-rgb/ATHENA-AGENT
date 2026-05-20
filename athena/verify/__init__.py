"""Verified-execution loop (T5-04).

Fuses the three Tier-5 pieces — checkpointing (T3-03), LSP
diagnostics (T5-03), and the sandboxed runner (T5-02) — into one
post-write verification cycle:

    checkpoint → write → diagnose → run → on failure, surface +
    offer one-step rollback.

Thin by design. The hard work lives in the dependencies; this
package sequences them and handles the failure UX.
"""

from .outcome import VerificationOutcome


def __getattr__(name: str):
    """Lazy access to :class:`VerifiedExecution` — the loop pulls
    every Tier-5 dependency at import time; loading it on demand
    keeps the outcome-only surface lightweight (callers that just
    want to inspect a logged outcome shouldn't pay for it)."""
    if name == "VerifiedExecution":
        from .loop import VerifiedExecution

        return VerifiedExecution
    raise AttributeError(f"module 'athena.verify' has no attribute {name!r}")


__all__ = ["VerificationOutcome", "VerifiedExecution"]
