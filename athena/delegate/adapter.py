"""Target-CLI invocation, fully isolated (T6-03.1).

This module is the **only** place in athena that knows how to
invoke the configured external coding CLI. Vendor specifics —
the executable name, the non-interactive subcommand, the
output-format flag, how to parse exit semantics — live here and
*only* here. Swapping target CLIs is a one-file edit.

The adapter has one job: run the delegate non-interactively in
``cwd`` with a wall-clock timeout, capturing stdout / stderr /
exit code. If the delegate executes code as part of doing the
task, that execution runs inside the delegate's process — but
the adapter itself can wrap the *whole* invocation in the T5-02
sandbox when the operator opts in (``cli_delegate_sandbox=True``),
which gives the delegate a read-only system root + writable
worktree only — defense-in-depth on top of any sandboxing the
delegate may do internally.

Two execution paths, picked at construction time:

  sandbox=None         direct subprocess.run, the safe default
                       when the delegate is trusted and the
                       worktree itself is the boundary
  sandbox=<run-fn>     route through the sandbox runner; the
                       delegate command is wrapped in bwrap
                       (same semantics as T5-04 verify_command)
"""

from __future__ import annotations

import dataclasses
import logging
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class DelegateResult:
    """Outcome of one delegate invocation.

    ``status`` is the high-level state the caller surfaces:

      ``done``     delegate exited within the timeout (exit_code
                   may still be non-zero — that's a delegate
                   failure, not a wrapping failure)
      ``timeout``  hit the wall-clock limit; delegate killed
      ``error``    couldn't even start the delegate (binary
                   missing, etc.)
    """

    status: str  # done | timeout | error
    exit_code: int
    stdout: str
    stderr: str
    sandboxed: bool


# Sandbox-runner signature alias — the runner accepts a command +
# cfg + workspace + timeout_s and returns a RunResult-shaped
# object. We type it loosely to avoid an import cycle with
# athena.sandbox.runner.
SandboxRunFn = Callable[..., Any]


class DelegateAdapter:
    """Adapter for invoking the configured external coding CLI.

    Construction takes:

      cfg                     athena Config (reads cli_delegate_*)
      sandbox_run             optional sandbox runner; when set,
                              the delegate runs under bwrap (the
                              same wrap T5-04 uses for
                              verify_command)

    Surface:

      ``run(task, *, cwd, timeout_s, env=None) -> DelegateResult``

    The command template is read from
    ``cfg.cli_delegate_command`` and rendered with ``{task}``
    substitution. Operators set this at build time to whatever
    the target CLI's non-interactive exec mode looks like
    (e.g. ``"codex exec --quiet {task}"`` or
    ``"aider --message {task} --yes"``). The template is
    tokenised via :mod:`shlex` BEFORE substitution so a task
    containing spaces / quotes stays one argv element.
    """

    def __init__(self, cfg: Any, *, sandbox_run: SandboxRunFn | None = None):
        self.cfg = cfg
        self.sandbox_run = sandbox_run

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        task: str,
        *,
        cwd: Path,
        timeout_s: float,
        env: dict[str, str] | None = None,
    ) -> DelegateResult:
        """Run the configured delegate on ``task`` in ``cwd`` with
        a wall-clock ``timeout_s``.

        Returns a :class:`DelegateResult`. Never raises into the
        agent loop — every failure mode maps to a status the
        caller can surface to the user."""
        argv, command_str = self._build_argv(task)
        if argv is None:
            return DelegateResult(
                status="error",
                exit_code=-1,
                stdout="",
                stderr="cli_delegate_command not configured",
                sandboxed=False,
            )

        if self.sandbox_run is not None:
            return self._run_sandboxed(command_str, cwd=cwd, timeout_s=timeout_s)
        return self._run_direct(argv, cwd=cwd, timeout_s=timeout_s, env=env)

    # ------------------------------------------------------------------
    # Argv construction — the build-time isolation point
    # ------------------------------------------------------------------

    def _build_argv(self, task: str) -> tuple[list[str] | None, str]:
        """Render the command template into an argv list + a
        shell-form string (for the sandbox path, which always
        goes through bash -c).

        The template uses ``{task}`` as the substitution
        placeholder. Tokenisation happens BEFORE substitution so
        the task text — which may contain spaces, quotes, or
        shell metacharacters — never gets split or re-interpreted
        as separate arguments / commands.
        """
        template = getattr(self.cfg, "cli_delegate_command", None)
        if not template:
            return None, ""
        # Tokenise the template into argv pieces, then substitute
        # {task} into each piece that contains it. Empty {task}
        # substitution keeps the placeholder visible in the
        # rendered string for logging.
        pieces = shlex.split(str(template))
        rendered = [p.replace("{task}", task) for p in pieces]
        # Build a shell-form string for sandbox / logging. shlex
        # quotes each element so re-parsing reproduces the argv.
        command_str = " ".join(shlex.quote(p) for p in rendered)
        return rendered, command_str

    # ------------------------------------------------------------------
    # Direct (non-sandboxed) path
    # ------------------------------------------------------------------

    def _run_direct(
        self,
        argv: list[str],
        *,
        cwd: Path,
        timeout_s: float,
        env: dict[str, str] | None,
    ) -> DelegateResult:
        try:
            proc = subprocess.run(
                argv,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=env,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            stdout = (e.stdout or "") if isinstance(e.stdout, str) else ""
            stderr = (e.stderr or "") if isinstance(e.stderr, str) else ""
            return DelegateResult(
                status="timeout",
                exit_code=124,
                stdout=stdout,
                stderr=stderr + f"\n[delegate] killed after {timeout_s:.0f}s",
                sandboxed=False,
            )
        except (FileNotFoundError, OSError) as e:
            return DelegateResult(
                status="error",
                exit_code=127,
                stdout="",
                stderr=f"[delegate] could not spawn: {e}",
                sandboxed=False,
            )
        return DelegateResult(
            status="done",
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            sandboxed=False,
        )

    # ------------------------------------------------------------------
    # Sandboxed path — defense-in-depth via T5-02
    # ------------------------------------------------------------------

    def _run_sandboxed(
        self,
        command_str: str,
        *,
        cwd: Path,
        timeout_s: float,
    ) -> DelegateResult:
        """Run via the injected sandbox runner. The same bwrap
        wrap T5-04 uses for verify_command — read-only system,
        writable worktree only, no network by default."""
        try:
            result = self.sandbox_run(  # type: ignore[misc]
                command_str,
                cfg=self.cfg,
                workspace=cwd,
                timeout_s=timeout_s,
            )
        except Exception as e:  # noqa: BLE001
            return DelegateResult(
                status="error",
                exit_code=-1,
                stdout="",
                stderr=f"[delegate] sandbox runner failed: {e}",
                sandboxed=True,
            )
        exit_code = int(getattr(result, "exit_code", -1))
        stdout = str(getattr(result, "stdout", "") or "")
        stderr = str(getattr(result, "stderr", "") or "")
        # The runner returns exit_code=124 on timeout (matches
        # T5-04's contract). Surface that as our timeout status.
        status = "timeout" if exit_code == 124 else "done"
        return DelegateResult(
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            sandboxed=True,
        )
