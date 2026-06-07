"""/review — code review of pending changes (or a specified diff)."""

from __future__ import annotations

from typing import Any

from . import command


@command("review")
def cmd_review(agent: Any, arg: str = "") -> str:
    target = arg.strip() or "the pending uncommitted changes"
    return (
        f"Review {target}. Run `git status` and `git diff` (or `git diff "
        f"{arg}` if a ref was provided) via Bash, then for each non-trivial "
        "change point out:\n"
        "- correctness issues (bugs, edge cases, off-by-one)\n"
        "- security issues (injection, auth, secrets, OWASP top-10)\n"
        "- maintainability issues (dead code, oversized abstractions, "
        "hidden state, broken invariants)\n"
        "- style/consistency mismatches with the rest of the codebase\n\n"
        "Focus on substantive issues. Reference exact `file:line` for each "
        "finding. Keep the report concise — under 30 lines unless the "
        "diff is large. End with a one-sentence overall assessment."
    )


@command("security-review")
def cmd_security_review(agent: Any, arg: str = "") -> str:
    target = arg.strip() or "the pending uncommitted changes"
    return (
        f"Perform a security review of {target}. Run `git diff` via Bash, "
        "then look specifically for:\n"
        "- Injection (SQL, command, XSS, path traversal, SSRF)\n"
        "- Auth/authz issues, broken access control, IDOR\n"
        "- Secrets in code or config\n"
        "- Crypto misuse, weak randomness, unsafe deserialization\n"
        "- Logic bugs that could be exploited (race conditions, TOCTOU)\n"
        "- Dependency concerns (new packages, version downgrades)\n\n"
        "Reference `file:line` for each finding. Don't report stylistic "
        "issues unless they map to a security risk."
    )
