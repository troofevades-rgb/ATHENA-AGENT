"""External coding-CLI delegation (T6-03).

Athena can delegate a scoped task to another agentic coding CLI:

  ``delegate_to_cli(task, repo_path, ...)``

runs the configured external CLI inside an isolated git worktree,
captures the resulting diff, and surfaces it for review. The
delegate **never** auto-merges and its output is treated as
untrusted — the worktree isolation + the explicit merge-or-discard
next step are the guardrails.

Target-CLI specifics (invocation, flags, output format) live in
:mod:`athena.delegate.adapter` so a vendor / tool change touches
one file.
"""

from .adapter import DelegateAdapter, DelegateResult
from .cli import delegate_to_cli

__all__ = ["DelegateAdapter", "DelegateResult", "delegate_to_cli"]
