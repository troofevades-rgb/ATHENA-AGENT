"""Verified-execution loop (T5-04.2).

One :class:`VerifiedExecution` instance + one ``verify_write``
call wraps a single file write with:

  1. **Capture** — snapshot the pre-write state via the active
     :class:`athena.agent.checkpoints.CheckpointManager` (T3-03).
     A failing checkpoint never blocks the write — the rollback
     offer just won't appear in the report.
  2. **Diagnose** — call :func:`athena.tools.diagnose.diagnose_paths`
     on the written path (T5-03). Errors that are *new* relative
     to the pre-write baseline count as introduced; carried-over
     errors don't trigger a failure.
  3. **Run** — when ``verify_on_write == "diagnose+run"`` and a
     ``verify_command`` is configured, run it under the sandbox
     runner (T5-02). Non-zero exit → failed_run.
  4. **Resolve** — pass returns a clean outcome; failure either
     auto-rolls-back (``verify_auto_rollback=True``) or returns
     a failed outcome whose ``.report()`` carries the rollback
     hint.

The orchestrator is sync end-to-end to match athena's surfaces
(checkpoints, LSP client, sandbox runner are all sync). Tests
sub in fakes for each leg via the constructor's optional
``checkpoints=``, ``diagnose=``, ``runner=`` injection points so
no real LSP / sandbox is spun up.

Goal-loop hook (deferred T5-07): ``latest_outcome`` accessor
returns the most recent :class:`VerificationOutcome` so a future
goal-evaluation loop can consult it without re-running the
verification. Read-only; the loop owns writes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .outcome import Outcome, VerificationOutcome

logger = logging.getLogger(__name__)


# Injectable function signatures. Kept narrow so the test doubles
# don't need to fake the full LSP / sandbox machinery.
DiagnoseFn = Callable[[list[str]], list[Any]]
RunFn = Callable[..., Any]  # cfg-aware run(command, *, cfg, workspace, timeout_s)


class VerifiedExecution:
    """One verifier per session.

    Construction is dependency-injected so tests can sub in
    fakes for diagnose / run / checkpoint manager without
    monkey-patching module-level imports.

    Default wiring (used by production callers) resolves at call
    time so a stale snapshot of ``load_config`` taken at
    construction doesn't pin behaviour for the session.
    """

    def __init__(
        self,
        *,
        cfg: Any = None,
        diagnose: DiagnoseFn | None = None,
        runner: RunFn | None = None,
        checkpoint_manager: Any | None = None,
        workspace: Path | str | None = None,
    ) -> None:
        self._cfg = cfg
        self._diagnose_override = diagnose
        self._runner_override = runner
        self._checkpoints_override = checkpoint_manager
        self._workspace = Path(workspace) if workspace else None
        self._latest: VerificationOutcome | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify_write(
        self,
        path: str | Path,
        *,
        retry_fn: Callable[[VerificationOutcome], None] | None = None,
    ) -> VerificationOutcome:
        """Run the full capture → diagnose → (run) → resolve cycle
        on a single just-written file path.

        ``retry_fn`` lets the caller plug in a "fix it and try
        again" hook. When ``verify_auto_retry`` is set and the
        cycle fails, the loop calls ``retry_fn(outcome)`` (which
        is expected to perform a corrected write at the same
        path), then re-verifies. The number of retries is capped
        at ``verify_max_retries`` and the per-attempt counter is
        carried on the resulting outcome.

        Never raises: any internal error in a verification leg
        becomes a logged debug + a ``skipped`` outcome so the
        post-write hook never blocks the agent on its own bugs.
        """
        cfg = self._cfg if self._cfg is not None else self._load_cfg()

        # Single-shot path: just one cycle, no retry.
        outcome = self._verify_once(path, cfg=cfg)
        self._latest = outcome

        if outcome.passed:
            return outcome
        if not getattr(cfg, "verify_auto_retry", False):
            return outcome
        if retry_fn is None:
            return outcome

        max_retries = int(getattr(cfg, "verify_max_retries", 2))
        for attempt in range(1, max_retries + 1):
            try:
                retry_fn(outcome)
            except Exception as e:  # noqa: BLE001
                logger.debug("verify_write: retry_fn raised, giving up: %s", e)
                return outcome
            outcome = self._verify_once(path, cfg=cfg)
            outcome.retries = attempt
            self._latest = outcome
            if outcome.passed:
                return outcome
        return outcome

    def _verify_once(self, path: str | Path, *, cfg: Any) -> VerificationOutcome:
        """One capture → diagnose → run cycle without retry."""
        path_str = str(path)
        mode = getattr(cfg, "verify_on_write", "diagnose")

        # Early out: verification disabled.
        if mode == "off":
            return VerificationOutcome(path=path_str, outcome="skipped")

        # 1. Pre-write checkpoint (best effort).
        checkpoint_id = self._capture_checkpoint(path_str)

        # 2. Diagnose leg.
        try:
            diagnose_fn = self._resolve_diagnose()
            new_diagnostics = diagnose_fn([path_str])
        except Exception as e:  # noqa: BLE001
            logger.debug("verify_write: diagnose leg raised: %s", e)
            new_diagnostics = []

        introduced = self._extract_errors(new_diagnostics)
        if introduced:
            return self._finalize_failure(
                VerificationOutcome(
                    path=path_str,
                    outcome="failed_diagnostics",
                    checkpoint_id=checkpoint_id,
                    introduced_errors=introduced,
                ),
                cfg=cfg,
            )

        # 3. Run leg (only when configured).
        if mode == "diagnose+run" and getattr(cfg, "verify_command", None):
            run_outcome = self._run_command(path_str, cfg, checkpoint_id)
            if run_outcome is not None:
                return run_outcome

        # 4. Passed.
        return VerificationOutcome(
            path=path_str,
            outcome="passed",
            checkpoint_id=checkpoint_id,
        )

    @property
    def latest_outcome(self) -> VerificationOutcome | None:
        """Read-only handle to the most recent outcome. T5-07's
        goal-evaluation loop will consult this to decide whether
        a turn made forward progress."""
        return self._latest

    # ------------------------------------------------------------------
    # Internals — each leg is one private method so tests can
    # exercise them in isolation without going through verify_write.
    # ------------------------------------------------------------------

    def _capture_checkpoint(self, path_str: str) -> str | None:
        """Capture a pre-write checkpoint via T3-03. Returns the
        checkpoint id, or None if no manager is active or the
        capture failed (a failed snapshot must never block the
        write itself)."""
        mgr = self._resolve_checkpoint_manager()
        if mgr is None:
            return None
        try:
            cp = mgr.create(label=f"pre-write-{Path(path_str).name}")
        except Exception as e:  # noqa: BLE001
            logger.debug("verify_write: checkpoint capture failed: %s", e)
            return None
        return getattr(cp, "id", None)

    def _resolve_diagnose(self) -> DiagnoseFn:
        if self._diagnose_override is not None:
            return self._diagnose_override
        # Late import — T5-03 LSP shouldn't be required for verify
        # to be *imported*, only to actually diagnose.
        from ..tools.diagnose import diagnose_paths

        return diagnose_paths

    def _resolve_runner(self) -> RunFn:
        if self._runner_override is not None:
            return self._runner_override
        from ..sandbox.runner import run as default_run

        return default_run

    def _resolve_checkpoint_manager(self) -> Any:
        if self._checkpoints_override is not None:
            return self._checkpoints_override
        from ..agent.checkpoints import get_active_checkpoint_manager

        return get_active_checkpoint_manager()

    def _extract_errors(self, diagnostics: list[Any]) -> list[str]:
        """Pull error-severity diagnostic messages out of a
        :class:`athena.lsp.client.Diagnostic` list, formatted for
        the report. Anything missing the ``is_error`` attribute is
        treated as non-fatal so unfamiliar shapes don't trigger a
        false failure."""
        out: list[str] = []
        for d in diagnostics:
            try:
                if not getattr(d, "is_error", False):
                    continue
            except Exception:  # noqa: BLE001
                continue
            line = getattr(d, "line", "?")
            col = getattr(d, "col", "?")
            code = getattr(d, "code", "") or ""
            msg = getattr(d, "message", "")
            code_part = f" [{code}]" if code else ""
            out.append(f"line {line}:{col}{code_part} {msg}")
        return out

    def _run_command(
        self,
        path_str: str,
        cfg: Any,
        checkpoint_id: str | None,
    ) -> VerificationOutcome | None:
        """Run ``cfg.verify_command`` and return a failed_run
        outcome on non-zero exit, or None on success (so the
        caller can fall through to the passed-state branch)."""
        command = getattr(cfg, "verify_command", None)
        if not command:
            return None
        timeout_s = float(getattr(cfg, "verify_run_timeout_s", 120.0))
        try:
            run_fn = self._resolve_runner()
            result = run_fn(
                command,
                cfg=cfg,
                workspace=self._workspace,
                timeout_s=timeout_s,
            )
        except Exception as e:  # noqa: BLE001
            # Distinguish "policy denied this command" (operator
            # config issue) from "the runner itself errored" (flaky
            # verifier) so the user-facing rollback hint can describe
            # the actual cause. Lazy import keeps the verify loop
            # decoupled from the sandbox subsystem on module load.
            try:
                from ..sandbox.runner import BlockedByPolicyError
            except ImportError:
                BlockedByPolicyError = ()  # type: ignore[assignment]
            blocked = isinstance(e, BlockedByPolicyError) if BlockedByPolicyError else False
            outcome: Outcome = "blocked_by_policy" if blocked else "failed_run"
            stderr_msg = (
                f"verify command blocked by policy: {e}"
                if blocked
                else f"verify runner errored: {e}"
            )
            logger.debug("verify_write: run leg raised (%s): %s", outcome, e)
            return self._finalize_failure(
                VerificationOutcome(
                    path=path_str,
                    outcome=outcome,
                    checkpoint_id=checkpoint_id,
                    run_exit_code=-1,
                    run_stderr_tail=stderr_msg,
                ),
                cfg=cfg,
            )

        if getattr(result, "succeeded", result.exit_code == 0):
            return None

        return self._finalize_failure(
            VerificationOutcome(
                path=path_str,
                outcome="failed_run",
                checkpoint_id=checkpoint_id,
                run_exit_code=getattr(result, "exit_code", -1),
                run_stderr_tail=_tail(getattr(result, "stderr", "") or ""),
            ),
            cfg=cfg,
        )

    def _finalize_failure(
        self,
        outcome: VerificationOutcome,
        *,
        cfg: Any,
    ) -> VerificationOutcome:
        """Branch on ``verify_auto_rollback`` to either keep the
        outcome as-is (so the report carries the rollback hint)
        or auto-revert and mark ``rolled_back=True``."""
        if not getattr(cfg, "verify_auto_rollback", False):
            return outcome
        if not outcome.checkpoint_id:
            logger.debug("verify_auto_rollback set but no checkpoint to revert to")
            return outcome
        mgr = self._resolve_checkpoint_manager()
        if mgr is None:
            return outcome
        try:
            mgr.rollback_to(outcome.checkpoint_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("verify_auto_rollback failed: %s", e)
            return outcome
        outcome.rolled_back = True
        return outcome

    def _load_cfg(self) -> Any:
        from ..config import load_config

        return load_config()


def _tail(text: str, *, max_bytes: int = 500) -> str:
    """Trim ``text`` to its last ``max_bytes`` bytes with an
    ellipsis prefix. Matches the format the outcome report
    expects."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    snipped = encoded[-max_bytes:].decode("utf-8", errors="replace")
    return "...\n" + snipped
