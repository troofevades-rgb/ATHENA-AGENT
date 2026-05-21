"""Worktree-isolated CLI delegation (T6-03).

Surface comes in two layers:

  Worktree helpers (T6-03.1)
    :func:`prepare_worktree`  create a fresh branch + worktree
                              from a base ref; returns
                              :class:`WorktreeHandle`
    :func:`capture_diff`      `git diff <base>` from inside the
                              worktree
    :func:`cleanup_worktree`  best-effort teardown; safe no-op
                              when the worktree is gone

  Delegation tool (T6-03.2)
    :func:`delegate_to_cli`   the model-callable tool

Vendor-CLI specifics live in :mod:`athena.delegate.adapter`.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DelegateError(RuntimeError):
    """Raised by worktree / git operations the caller MUST surface.

    Adapter / delegate failures (timeout, non-zero exit) are
    *not* errors — they're :class:`DelegateResult` outcomes. This
    exception is for "git itself is unavailable" / "the repo is
    invalid" — the kind of pre-flight failure that should stop
    the delegation entirely.
    """


# ---------------------------------------------------------------------------
# Worktree handle
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class WorktreeHandle:
    """One isolated worktree the delegate writes into.

    ``branch``     fresh branch the worktree is checked out on
    ``worktree``   absolute path; sits OUTSIDE the main checkout
    ``base_ref``   the commit/branch the diff is taken against
    """

    branch: str
    worktree: Path
    base_ref: str


# ---------------------------------------------------------------------------
# Worktree helpers
# ---------------------------------------------------------------------------


def prepare_worktree(
    repo_path: Path,
    *,
    base_ref: str = "HEAD",
    worktree_root: Path | None = None,
    branch_prefix: str = "delegate",
) -> WorktreeHandle:
    """Create a fresh branch + worktree from ``base_ref``.

    Returns a :class:`WorktreeHandle`. The worktree lives under
    ``worktree_root`` (defaults to the system temp dir) so it
    sits outside the main checkout — git's own worktree
    machinery enforces the isolation.

    Raises :class:`DelegateError` if git isn't usable / the repo
    isn't a git repo / the base ref doesn't resolve.
    """
    repo_path = Path(repo_path).resolve()
    if not (repo_path / ".git").exists() and not _is_git_dir(repo_path):
        raise DelegateError(f"not a git repository: {repo_path}")

    base_root = (
        Path(worktree_root).resolve()
        if worktree_root
        else Path(tempfile.gettempdir())
    )
    base_root.mkdir(parents=True, exist_ok=True)
    suffix = uuid.uuid4().hex[:12]
    branch = f"{branch_prefix}/{suffix}"
    worktree = base_root / f"{branch_prefix}-{suffix}"

    # `git worktree add -b <branch> <path> <base_ref>` checks
    # out ``base_ref`` on the new branch into ``path``. Fails
    # cleanly if the path already exists.
    result = _git(
        repo_path,
        "worktree",
        "add",
        "-b",
        branch,
        str(worktree),
        base_ref,
    )
    if result.returncode != 0:
        raise DelegateError(
            f"git worktree add failed: {result.stderr.strip() or 'unknown error'}"
        )
    return WorktreeHandle(branch=branch, worktree=worktree, base_ref=base_ref)


def capture_diff(handle: WorktreeHandle) -> str:
    """Return the diff the delegate produced — ``git diff <base>``
    run from inside the worktree. Empty string when the delegate
    didn't change anything (still a valid outcome to surface).

    Includes both committed AND uncommitted changes via
    ``git diff <base>`` (which compares HEAD vs base) followed by
    the worktree's unstaged diff — concatenated. This way a
    delegate that committed AND a delegate that just edited
    files both get fully captured.
    """
    committed = _git(
        handle.worktree, "diff", handle.base_ref, "HEAD"
    )
    # Unstaged + untracked. We add then diff --cached so newly-
    # created files show up too, then restore the index by
    # reset --mixed afterwards is overkill — instead use
    # `git diff <base> -- .` which compares the working tree
    # against the base ref directly.
    working = _git(handle.worktree, "diff", handle.base_ref)
    pieces: list[str] = []
    if committed.stdout.strip():
        pieces.append(committed.stdout)
    if working.stdout.strip():
        # Skip if it's identical to the committed diff (delegate
        # only committed, didn't leave uncommitted edits).
        if not committed.stdout or committed.stdout != working.stdout:
            pieces.append(working.stdout)
    return "\n".join(pieces).rstrip()


def cleanup_worktree(handle: WorktreeHandle, *, repo_path: Path) -> bool:
    """Tear down the worktree + branch. Best-effort: returns
    True when both pieces were removed cleanly, False when the
    worktree / branch had already been moved or removed.

    Cleanup is NOT automatic after :func:`delegate_to_cli`
    finishes — the caller decides whether to merge the diff
    (then clean) or just discard (then clean). Leaving the
    worktree in place is the safe default; cleanup is opt-in
    per call site.
    """
    repo_path = Path(repo_path).resolve()
    ok = True

    # `git worktree remove --force` drops the worktree dir +
    # de-registers it from the main repo's worktree list.
    remove = _git(repo_path, "worktree", "remove", "--force", str(handle.worktree))
    if remove.returncode != 0:
        ok = False
        logger.debug(
            "worktree remove failed for %s: %s",
            handle.worktree,
            remove.stderr.strip(),
        )

    # The branch sticks around after worktree removal; drop it
    # too so the repo doesn't accumulate delegate/<uuid>
    # branches forever.
    branch_delete = _git(repo_path, "branch", "-D", handle.branch)
    if branch_delete.returncode != 0:
        ok = False
        logger.debug(
            "branch delete failed for %s: %s",
            handle.branch,
            branch_delete.stderr.strip(),
        )
    return ok


# ---------------------------------------------------------------------------
# git wrapper
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str, timeout_s: float = 30.0) -> subprocess.CompletedProcess:
    """Run ``git <args>`` in ``cwd``. Captures both streams,
    never raises on non-zero exit (caller branches on
    ``returncode``)."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            shell=False,
            check=False,
        )
    except FileNotFoundError as e:
        raise DelegateError(f"git not on PATH: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise DelegateError(
            f"git {' '.join(args)} timed out after {timeout_s:.0f}s"
        ) from e


def _is_git_dir(p: Path) -> bool:
    """A bare repo / linked worktree has a `HEAD` file instead of
    a `.git` subdir. Accept either shape."""
    return (p / "HEAD").exists() and (p / "refs").exists()


# ---------------------------------------------------------------------------
# delegate_to_cli — registered in T6-03.2 (tool decorator there)
# ---------------------------------------------------------------------------


# Symbol placeholder — the actual @tool-decorated entry point
# lives below T6-03.2 patch. Importing this module now should
# expose only the worktree helpers; the tool gets attached in
# the next sub-prompt.


def delegate_to_cli(
    task: str = "",
    repo_path: str = "",
    base_ref: str = "HEAD",
    timeout_s: int | None = None,
    **_kwargs: Any,
) -> str:
    """Placeholder — implemented in T6-03.2."""
    raise NotImplementedError("T6-03.2 implements this tool")
