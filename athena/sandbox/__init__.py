"""Sandbox layer for athena's Bash tool (T5-02R).

Wraps shell command execution in a bubblewrap (bwrap) jail when
enabled — read-only system, writable workspace only, no network by
default. The :mod:`athena.safety.shell_policy` denylist still runs
first as the security floor; the sandbox is defense-in-depth on
top.

Linux-only; non-Linux / no-bwrap deployments either warn-and-fall-through
or refuse per :attr:`cfg.sandbox_fallback`.
"""

from .bwrap import build_bwrap_command, is_bwrap_available

__all__ = ["build_bwrap_command", "is_bwrap_available"]
