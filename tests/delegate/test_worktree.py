"""Worktree management tests (T6-03.1).

git is mocked at the subprocess level so no real .git operations
run. The assertions pin the argv athena hands to git plus the
isolation contract: the main checkout is never touched, the
worktree lives outside it, the diff comes from the worktree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.delegate import cli as cli_mod
from athena.delegate.cli import (
    DelegateError,
    WorktreeHandle,
    capture_diff,
    cleanup_worktree,
    prepare_worktree,
)


# ---------------------------------------------------------------------------
# subprocess.run stub
# ---------------------------------------------------------------------------


class _GitStub:
    """Records every git invocation + returns canned results.

    Default behaviour: every git call succeeds with empty
    stdout/stderr. Set ``responses`` to a list of dicts to
    override sequentially; set ``raise_on_first`` to surface a
    raised exception on the first call.
    """

    def __init__(
        self,
        *,
        responses: list[dict] | None = None,
        always_return: dict | None = None,
        raise_on_first: Exception | None = None,
    ):
        self.calls: list[tuple[list[str], str]] = []
        self.responses = list(responses or [])
        self.always_return = always_return or {"returncode": 0, "stdout": "", "stderr": ""}
        self.raise_on_first = raise_on_first

    def __call__(self, argv, **kwargs):
        if self.raise_on_first is not None:
            exc = self.raise_on_first
            self.raise_on_first = None
            raise exc
        self.calls.append((list(argv), str(kwargs.get("cwd", ""))))
        if self.responses:
            payload = self.responses.pop(0)
        else:
            payload = dict(self.always_return)
        return subprocess.CompletedProcess(
            args=argv,
            returncode=int(payload.get("returncode", 0)),
            stdout=str(payload.get("stdout", "")),
            stderr=str(payload.get("stderr", "")),
        )


def _make_repo(tmp_path: Path) -> Path:
    """Make ``tmp_path/repo`` look like a git repo to the
    pre-flight check (`.git` exists)."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    return repo


# ---------------------------------------------------------------------------
# prepare_worktree
# ---------------------------------------------------------------------------


def test_worktree_add_on_fresh_branch(tmp_path: Path, monkeypatch):
    """prepare_worktree calls `git worktree add -b <branch> <path>
    <base_ref>` with a freshly-minted branch name + worktree
    outside the main checkout."""
    stub = _GitStub()
    monkeypatch.setattr(cli_mod, "subprocess", SimpleNamespace(
        run=stub,
        CompletedProcess=subprocess.CompletedProcess,
        TimeoutExpired=subprocess.TimeoutExpired,
    ))
    repo = _make_repo(tmp_path)
    worktree_root = tmp_path / "worktrees"

    handle = prepare_worktree(
        repo, base_ref="HEAD", worktree_root=worktree_root
    )

    # The branch prefix and worktree dir both encode the same uuid
    # suffix.
    assert handle.branch.startswith("delegate/")
    assert handle.worktree.name.startswith("delegate-")
    assert handle.worktree.name.endswith(handle.branch.split("/", 1)[1])
    assert handle.base_ref == "HEAD"

    # Exactly one git invocation: worktree add.
    assert len(stub.calls) == 1
    argv, cwd = stub.calls[0]
    assert argv[0] == "git"
    assert argv[1:4] == ["worktree", "add", "-b"]
    assert argv[4] == handle.branch
    assert argv[5] == str(handle.worktree)
    assert argv[6] == "HEAD"
    # cwd is the repo, not the worktree (worktree doesn't exist
    # yet — git creates it).
    assert cwd == str(repo)


def test_worktree_outside_main_tree(tmp_path: Path, monkeypatch):
    """The worktree path is NEVER inside the repo. This is the
    isolation invariant — the delegate cannot clobber the main
    checkout because git's own worktree machinery forbids
    overlapping paths."""
    stub = _GitStub()
    monkeypatch.setattr(cli_mod, "subprocess", SimpleNamespace(
        run=stub,
        CompletedProcess=subprocess.CompletedProcess,
        TimeoutExpired=subprocess.TimeoutExpired,
    ))
    repo = _make_repo(tmp_path)
    worktree_root = tmp_path / "worktrees"

    handle = prepare_worktree(repo, worktree_root=worktree_root)
    assert worktree_root in handle.worktree.parents
    # Sanity: the worktree is NOT under the repo dir.
    assert repo not in handle.worktree.parents


def test_worktree_rejects_non_repo(tmp_path: Path):
    """A path without a .git dir is rejected pre-flight."""
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    with pytest.raises(DelegateError, match="not a git repository"):
        prepare_worktree(not_a_repo, worktree_root=tmp_path / "wt")


def test_worktree_surfaces_git_failure(tmp_path: Path, monkeypatch):
    """`git worktree add` returning non-zero → DelegateError
    carrying stderr."""
    stub = _GitStub(responses=[{"returncode": 1, "stderr": "fatal: bad ref"}])
    monkeypatch.setattr(cli_mod, "subprocess", SimpleNamespace(
        run=stub,
        CompletedProcess=subprocess.CompletedProcess,
        TimeoutExpired=subprocess.TimeoutExpired,
    ))
    repo = _make_repo(tmp_path)
    with pytest.raises(DelegateError, match="bad ref"):
        prepare_worktree(repo, worktree_root=tmp_path / "wt")


# ---------------------------------------------------------------------------
# capture_diff
# ---------------------------------------------------------------------------


def test_diff_captured_against_base(tmp_path: Path, monkeypatch):
    """capture_diff runs `git diff <base> HEAD` AND `git diff
    <base>` in the worktree and returns the captured text."""
    expected_committed = "diff --git a/x b/x\n+committed change\n"
    expected_working = "diff --git a/y b/y\n+working change\n"
    stub = _GitStub(
        responses=[
            {"returncode": 0, "stdout": expected_committed},
            {"returncode": 0, "stdout": expected_working},
        ]
    )
    monkeypatch.setattr(cli_mod, "subprocess", SimpleNamespace(
        run=stub,
        CompletedProcess=subprocess.CompletedProcess,
        TimeoutExpired=subprocess.TimeoutExpired,
    ))

    handle = WorktreeHandle(
        branch="delegate/abc",
        worktree=tmp_path / "wt",
        base_ref="HEAD~1",
    )
    diff = capture_diff(handle)
    assert "committed change" in diff
    assert "working change" in diff

    # Both git invocations were rooted in the worktree, not the
    # main repo.
    assert len(stub.calls) == 2
    for argv, cwd in stub.calls:
        assert cwd == str(handle.worktree)
        assert argv[0] == "git" and argv[1] == "diff"


def test_diff_empty_when_no_changes(tmp_path: Path, monkeypatch):
    """A delegate that didn't change anything → empty diff. Not
    an error — surfacing 'no changes' is a valid outcome the
    caller wants to know about."""
    stub = _GitStub()  # both git diffs return empty stdout
    monkeypatch.setattr(cli_mod, "subprocess", SimpleNamespace(
        run=stub,
        CompletedProcess=subprocess.CompletedProcess,
        TimeoutExpired=subprocess.TimeoutExpired,
    ))
    handle = WorktreeHandle(
        branch="delegate/abc", worktree=tmp_path / "wt", base_ref="HEAD"
    )
    assert capture_diff(handle) == ""


def test_diff_dedupes_committed_and_working(tmp_path: Path, monkeypatch):
    """If the committed-vs-base diff is identical to the
    working-vs-base diff (delegate committed everything; nothing
    uncommitted), only one copy goes into the result — no
    duplication."""
    same = "diff --git a/x b/x\n+only change\n"
    stub = _GitStub(
        responses=[
            {"returncode": 0, "stdout": same},
            {"returncode": 0, "stdout": same},
        ]
    )
    monkeypatch.setattr(cli_mod, "subprocess", SimpleNamespace(
        run=stub,
        CompletedProcess=subprocess.CompletedProcess,
        TimeoutExpired=subprocess.TimeoutExpired,
    ))
    handle = WorktreeHandle(
        branch="delegate/abc",
        worktree=tmp_path / "wt",
        base_ref="HEAD",
    )
    diff = capture_diff(handle)
    # The "only change" line should appear exactly once.
    assert diff.count("+only change") == 1


# ---------------------------------------------------------------------------
# Main tree untouched contract
# ---------------------------------------------------------------------------


def test_main_tree_untouched(tmp_path: Path, monkeypatch):
    """Across prepare + capture, every git invocation against the
    MAIN repo is read-only (worktree add) or operates on the
    worktree path. No `git checkout` / `git reset` / `git commit`
    against the main repo's cwd."""
    stub = _GitStub()
    monkeypatch.setattr(cli_mod, "subprocess", SimpleNamespace(
        run=stub,
        CompletedProcess=subprocess.CompletedProcess,
        TimeoutExpired=subprocess.TimeoutExpired,
    ))
    repo = _make_repo(tmp_path)

    handle = prepare_worktree(repo, worktree_root=tmp_path / "wt")
    capture_diff(handle)

    forbidden = {"checkout", "reset", "commit", "merge", "rebase", "push"}
    for argv, cwd in stub.calls:
        if cwd == str(repo):
            # The only thing we do against the main repo cwd is
            # `git worktree add` — read-only against the user's
            # tree.
            assert argv[1] == "worktree", argv
            assert argv[2] == "add", argv
        # And no forbidden mutation verb appears anywhere.
        assert argv[1] not in forbidden, argv


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


def test_cleanup_removes_worktree_and_branch(tmp_path: Path, monkeypatch):
    """cleanup_worktree calls `git worktree remove --force`
    followed by `git branch -D <branch>` against the repo."""
    stub = _GitStub()
    monkeypatch.setattr(cli_mod, "subprocess", SimpleNamespace(
        run=stub,
        CompletedProcess=subprocess.CompletedProcess,
        TimeoutExpired=subprocess.TimeoutExpired,
    ))
    handle = WorktreeHandle(
        branch="delegate/abc",
        worktree=tmp_path / "wt",
        base_ref="HEAD",
    )
    repo = _make_repo(tmp_path)
    ok = cleanup_worktree(handle, repo_path=repo)
    assert ok is True

    cmds = [argv[1:3] for argv, _ in stub.calls]
    assert ["worktree", "remove"] in cmds
    assert ["branch", "-D"] in cmds
