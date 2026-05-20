"""``athena verify`` — one-shot verified-execution for a single file (T5-04.4).

Wraps :class:`athena.verify.loop.VerifiedExecution.verify_write`
behind a CLI. Useful for:

  * Running the verify cycle outside the agent loop (e.g. after a
    manual edit, or in CI).
  * Confirming a candidate ``verify_command`` is correctly wired
    before turning on ``verify_on_write="diagnose+run"`` for the
    agent.

Usage::

    athena verify <path>
    athena verify <path> --command "pytest -q tests/foo"
    athena verify <path> --command "ruff check" --no-sandbox

``--command`` forces the diagnose+run mode for this invocation
even when the config has it set to ``"diagnose"``. ``--no-sandbox``
disables the bwrap wrap for this invocation.

Exit code mirrors the outcome:
  0 = passed / skipped
  1 = failed_diagnostics
  2 = failed_run
  3 = path not found
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import load_config
from ..verify import VerifiedExecution


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="athena verify",
        description=(
            "Verify a file: run LSP diagnostics + an optional command "
            "under the sandbox, and report the result."
        ),
    )
    ap.add_argument("path", help="Path to verify.")
    ap.add_argument(
        "--command",
        default=None,
        help=(
            "Override config's verify_command. Setting this also "
            "forces diagnose+run mode for this invocation."
        ),
    )
    ap.add_argument(
        "--no-sandbox",
        action="store_true",
        help="Disable the bwrap sandbox for this run (config default unchanged).",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Override verify_run_timeout_s for this invocation.",
    )
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse(argv)
    target = Path(args.path).expanduser()
    if not target.exists():
        sys.stderr.write(f"error: {target} does not exist\n")
        return 3

    cfg = load_config()
    if args.command is not None:
        cfg.verify_command = args.command
        cfg.verify_on_write = "diagnose+run"
    if args.no_sandbox:
        cfg.sandbox_enabled = False
    if args.timeout is not None:
        cfg.verify_run_timeout_s = float(args.timeout)

    # CLI is a one-shot: no checkpoint manager active → outcome
    # carries no rollback hint, just the verify result. That's the
    # right behaviour outside an agent session.
    verifier = VerifiedExecution(cfg=cfg, workspace=Path.cwd())
    outcome = verifier.verify_write(target)
    sys.stdout.write(outcome.report() + "\n")

    if outcome.outcome == "passed" or outcome.outcome == "skipped":
        return 0
    if outcome.outcome == "failed_diagnostics":
        return 1
    if outcome.outcome == "failed_run":
        return 2
    return 0
