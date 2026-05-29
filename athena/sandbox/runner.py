"""Sandboxed runner — a standalone command-execution helper for
the verified-execution loop (T5-04).

T5-02R wrapped athena's interactive Bash tool's ``_spawn``. That's
the right place to put the sandbox for *agent-initiated* commands.
But the verified-execution loop needs to run *project-level*
commands (``pytest -q``, ``ruff check``, ``go vet ./...``) from
its own code path — without console output, without the
confirmation gate, and with structured stdout/stderr/exit_code
return rather than the streaming-string return Bash gives.

This module is a thin parallel: same bwrap wrapping, same
shell_policy denylist as the security floor, but driven from a
function-call surface rather than the tool dispatch.

  run(command, *, cfg, workspace=None, timeout_s=120) → RunResult

Returns a :class:`RunResult` with the three fields the verify
loop needs: ``exit_code``, ``stdout``, ``stderr``.
"""

from __future__ import annotations

import dataclasses
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..safety.shell_policy import DEFAULT_DENYLIST, ShellPolicy
from .bwrap import build_bwrap_command, is_bwrap_available

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class RunResult:
    """One sandboxed command's terminal state."""

    exit_code: int
    stdout: str
    stderr: str
    command: str
    sandboxed: bool

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


class BlockedByPolicyError(RuntimeError):
    """Raised when the shell_policy denylist refuses the command.
    The verify loop catches this and surfaces a clear reason."""


def run(
    command: str,
    *,
    cfg: Any,
    workspace: str | Path | None = None,
    timeout_s: float = 120.0,
) -> RunResult:
    """Run ``command`` under the bwrap sandbox when available.

    Decision tree:

    1. shell_policy denylist always runs first — denylisted →
       :class:`BlockedByPolicyError`.
    2. ``cfg.sandbox_enabled`` + bwrap available + Linux →
       wrap the inner ``bash -c command`` in bwrap argv.
    3. ``cfg.sandbox_enabled`` + bwrap unavailable +
       ``cfg.sandbox_fallback == "error"`` →
       :class:`BlockedByPolicyError` ("sandbox required but
       unavailable"). ``"warn"`` falls through to un-sandboxed.
    4. Otherwise — direct ``bash -c command`` (the
       shell_policy denylist is still the security floor).
    """
    ws = str(Path(workspace).resolve()) if workspace else None

    # 1. Denylist floor
    bash_cfg = getattr(cfg, "bash", None)
    if bash_cfg is not None:
        extras = tuple(bash_cfg.extra_denylist or ())
    else:
        # Fallback for stub cfg objects (test SimpleNamespace fixtures).
        extras = tuple(getattr(cfg, "bash_extra_denylist", ()) or ())
    policy = ShellPolicy(denylist=tuple(DEFAULT_DENYLIST) + extras)
    decision = policy.evaluate_denylist_only(command)
    if not decision.allowed:
        raise BlockedByPolicyError(
            f"shell policy refused the command: {decision.reason}"
        )

    # 2/3. Sandbox decision
    sandbox_enabled = bool(getattr(cfg, "sandbox_enabled", False))
    sandboxed = False
    argv: list[str]
    if sandbox_enabled:
        if is_bwrap_available():
            inner = ["/bin/bash", "-c", command]
            argv = build_bwrap_command(
                inner,
                workspace=ws or ".",
                allow_network=bool(getattr(cfg, "sandbox_allow_network", False)),
                writable_paths=list(
                    getattr(cfg, "sandbox_writable_paths", []) or []
                ),
            )
            sandboxed = True
        else:
            fallback = getattr(cfg, "sandbox_fallback", "warn")
            if fallback == "error":
                raise BlockedByPolicyError(
                    "sandbox_enabled but bubblewrap unavailable on this host"
                )
            logger.warning(
                "verify.sandbox.run: sandbox_enabled but unavailable; "
                "falling through to un-sandboxed (sandbox_fallback='warn')"
            )
            argv = _direct_argv(command)
    else:
        argv = _direct_argv(command)

    # Run.
    try:
        proc = subprocess.run(
            argv,
            cwd=ws,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        # Treat timeout as a non-zero exit with the partial stderr
        # so the verify loop can surface it as a failed_run.
        return RunResult(
            exit_code=124,
            stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
            stderr=(
                (e.stderr or "") if isinstance(e.stderr, str) else ""
            )
            + f"\n[verify] command timed out after {timeout_s:.0f}s",
            command=command,
            sandboxed=sandboxed,
        )
    except OSError as e:
        # Spawning the inner command itself failed (bash not on PATH,
        # etc.) — surface as a non-zero exit with the exception text
        # in stderr so the loop produces failed_run instead of crashing.
        return RunResult(
            exit_code=127,
            stdout="",
            stderr=f"[verify] failed to spawn command: {e}",
            command=command,
            sandboxed=sandboxed,
        )

    return RunResult(
        exit_code=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        command=command,
        sandboxed=sandboxed,
    )


def _direct_argv(command: str) -> list[str]:
    """Un-sandboxed argv for the inner shell. On POSIX we route
    through bash; on Windows we use the platform default (cmd) so
    the verify loop works on developer machines too, even though
    the sandbox itself is Linux-only."""
    if sys.platform == "win32":
        return ["cmd", "/C", command]
    return ["/bin/bash", "-c", command]
