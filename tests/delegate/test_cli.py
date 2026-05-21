"""Tests for the delegate_to_cli tool (T6-03.2).

Exercises the tool against stubbed git + stubbed adapter so no
real external CLI runs and no real .git operations fire. The
load-bearing invariants:

  * Scope required — empty task → rejected, no worktree created
  * Worktree isolation — every call goes through prepare_worktree
  * Never auto-merges — no merge/commit-to-main anywhere in the
    code path the tool exercises
  * Sandbox used when configured — sandbox_run is non-None on
    DelegateAdapter when cfg.cli_delegate_sandbox=True
  * Timeout → status=timeout, surfaced cleanly
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.delegate import cli as cli_mod
from athena.delegate.adapter import DelegateResult
from athena.delegate.cli import WorktreeHandle, delegate_to_cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(**overrides) -> SimpleNamespace:
    base = dict(
        cli_delegate_enabled=True,
        cli_delegate_command="codex exec {task}",
        cli_delegate_timeout_s=120.0,
        cli_delegate_worktree_root=None,
        cli_delegate_sandbox=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _GitStub:
    """Minimal git stub recording every invocation."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        # worktree add succeeds; diff returns sample text;
        # everything else returns empty.
        if argv[1:3] == ["worktree", "add"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[1] == "diff":
            return subprocess.CompletedProcess(
                argv,
                0,
                "diff --git a/x b/x\n+delegated change\n",
                "",
            )
        return subprocess.CompletedProcess(argv, 0, "", "")


def _patch_git(monkeypatch, stub: _GitStub) -> None:
    monkeypatch.setattr(
        cli_mod,
        "subprocess",
        SimpleNamespace(
            run=stub,
            CompletedProcess=subprocess.CompletedProcess,
            TimeoutExpired=subprocess.TimeoutExpired,
        ),
    )


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    return repo


# ---------------------------------------------------------------------------
# Scope guard
# ---------------------------------------------------------------------------


def test_delegation_requires_scope(tmp_path: Path, monkeypatch):
    """Empty task → rejected, NO worktree created (git stub
    recorded zero calls)."""
    stub = _GitStub()
    _patch_git(monkeypatch, stub)
    monkeypatch.setattr(cli_mod, "_load_cfg", lambda: _cfg())

    out = delegate_to_cli(task="", repo_path=str(_make_repo(tmp_path)))
    payload = json.loads(out)
    assert payload["status"] == "rejected"
    assert "scope" in payload["reason"]
    assert stub.calls == []  # the load-bearing assertion


def test_delegation_requires_repo_path(tmp_path: Path, monkeypatch):
    stub = _GitStub()
    _patch_git(monkeypatch, stub)
    monkeypatch.setattr(cli_mod, "_load_cfg", lambda: _cfg())

    out = delegate_to_cli(task="real task", repo_path="")
    payload = json.loads(out)
    assert payload["status"] == "rejected"
    assert stub.calls == []


# ---------------------------------------------------------------------------
# Config gating
# ---------------------------------------------------------------------------


def test_rejected_when_disabled(tmp_path: Path, monkeypatch):
    stub = _GitStub()
    _patch_git(monkeypatch, stub)
    monkeypatch.setattr(
        cli_mod, "_load_cfg", lambda: _cfg(cli_delegate_enabled=False)
    )

    out = delegate_to_cli(task="real task", repo_path=str(_make_repo(tmp_path)))
    payload = json.loads(out)
    assert payload["status"] == "rejected"
    assert "cli_delegate_enabled" in payload["reason"]
    assert stub.calls == []  # no git op fires


def test_rejected_when_no_command_configured(tmp_path: Path, monkeypatch):
    stub = _GitStub()
    _patch_git(monkeypatch, stub)
    monkeypatch.setattr(
        cli_mod, "_load_cfg", lambda: _cfg(cli_delegate_command=None)
    )

    out = delegate_to_cli(task="task", repo_path=str(_make_repo(tmp_path)))
    payload = json.loads(out)
    assert payload["status"] == "rejected"
    assert "cli_delegate_command" in payload["reason"]
    assert stub.calls == []


# ---------------------------------------------------------------------------
# Captures diff
# ---------------------------------------------------------------------------


def test_captures_diff(tmp_path: Path, monkeypatch):
    stub = _GitStub()
    _patch_git(monkeypatch, stub)
    monkeypatch.setattr(cli_mod, "_load_cfg", lambda: _cfg())

    # Adapter stub — pretend the delegate did its job cleanly.
    class _OkAdapter:
        def __init__(self, *, cfg, sandbox_run=None):
            self.cfg = cfg
            self.sandbox_run = sandbox_run

        def run(self, task, *, cwd, timeout_s):
            return DelegateResult(
                status="done",
                exit_code=0,
                stdout="delegate said: done",
                stderr="",
                sandboxed=bool(self.sandbox_run),
            )

    monkeypatch.setattr(
        "athena.delegate.adapter.DelegateAdapter", _OkAdapter
    )

    out = delegate_to_cli(
        task="add --json flag",
        repo_path=str(_make_repo(tmp_path)),
    )
    payload = json.loads(out)
    assert payload["status"] == "done"
    assert "delegated change" in payload["diff"]
    assert payload["branch"].startswith("delegate/")
    assert payload["worktree"]
    assert payload["exit_code"] == 0


# ---------------------------------------------------------------------------
# Never auto-merges — the invariant
# ---------------------------------------------------------------------------


def test_never_auto_merges(tmp_path: Path, monkeypatch):
    """Across the full delegation path, NO `git merge` / `git
    push` / `git commit` is invoked against the main repo. The
    only git commands that should fire are worktree add + diff."""
    stub = _GitStub()
    _patch_git(monkeypatch, stub)
    monkeypatch.setattr(cli_mod, "_load_cfg", lambda: _cfg())

    class _OkAdapter:
        def __init__(self, *, cfg, sandbox_run=None):
            pass

        def run(self, task, *, cwd, timeout_s):
            return DelegateResult(
                status="done", exit_code=0, stdout="", stderr="", sandboxed=False
            )

    monkeypatch.setattr(
        "athena.delegate.adapter.DelegateAdapter", _OkAdapter
    )

    delegate_to_cli(
        task="something",
        repo_path=str(_make_repo(tmp_path)),
    )
    forbidden = {"merge", "push", "commit", "rebase", "checkout", "reset"}
    for argv in stub.calls:
        # argv[1] is the git subcommand
        assert argv[1] not in forbidden, argv


def test_response_has_review_next_step(tmp_path: Path, monkeypatch):
    """The response carries a "review the diff" next_step that
    explicitly tells the caller athena never auto-merges — the
    user-visible contract."""
    stub = _GitStub()
    _patch_git(monkeypatch, stub)
    monkeypatch.setattr(cli_mod, "_load_cfg", lambda: _cfg())
    monkeypatch.setattr(
        "athena.delegate.adapter.DelegateAdapter",
        lambda **kw: SimpleNamespace(
            run=lambda task, cwd, timeout_s: DelegateResult(
                "done", 0, "", "", False
            )
        ),
    )

    out = delegate_to_cli(task="x", repo_path=str(_make_repo(tmp_path)))
    payload = json.loads(out)
    assert "review the diff" in payload["next_step"]
    # And the next_step suggests both paths — merge OR discard.
    assert "merge" in payload["next_step"]
    assert "discard" in payload["next_step"]
    # Pinning that the result NEVER applies the diff.
    assert payload["status"] != "merged"


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_timeout_kills_delegate(tmp_path: Path, monkeypatch):
    """Adapter returns status=timeout → tool surfaces it."""
    stub = _GitStub()
    _patch_git(monkeypatch, stub)
    monkeypatch.setattr(cli_mod, "_load_cfg", lambda: _cfg())

    class _TimeoutAdapter:
        def __init__(self, **_kw):
            pass

        def run(self, task, *, cwd, timeout_s):
            return DelegateResult(
                status="timeout",
                exit_code=124,
                stdout="",
                stderr="killed after 120s",
                sandboxed=False,
            )

    monkeypatch.setattr(
        "athena.delegate.adapter.DelegateAdapter", _TimeoutAdapter
    )

    out = delegate_to_cli(task="long task", repo_path=str(_make_repo(tmp_path)))
    payload = json.loads(out)
    assert payload["status"] == "timeout"
    assert payload["exit_code"] == 124
    assert "killed after" in payload["stderr"]


# ---------------------------------------------------------------------------
# Sandbox used when enabled
# ---------------------------------------------------------------------------


def test_sandbox_used_when_enabled(tmp_path: Path, monkeypatch):
    """cli_delegate_sandbox=True → DelegateAdapter is constructed
    with a non-None sandbox_run (the T5-02 runner)."""
    stub = _GitStub()
    _patch_git(monkeypatch, stub)
    monkeypatch.setattr(
        cli_mod, "_load_cfg", lambda: _cfg(cli_delegate_sandbox=True)
    )

    seen: dict[str, Any] = {}

    class _SpyAdapter:
        def __init__(self, *, cfg, sandbox_run=None):
            seen["sandbox_run"] = sandbox_run

        def run(self, task, *, cwd, timeout_s):
            return DelegateResult("done", 0, "", "", sandboxed=True)

    monkeypatch.setattr(
        "athena.delegate.adapter.DelegateAdapter", _SpyAdapter
    )

    delegate_to_cli(task="t", repo_path=str(_make_repo(tmp_path)))
    assert seen["sandbox_run"] is not None


def test_sandbox_not_used_when_disabled(tmp_path: Path, monkeypatch):
    """cli_delegate_sandbox=False → adapter constructed with
    sandbox_run=None; the delegate runs directly via
    subprocess."""
    stub = _GitStub()
    _patch_git(monkeypatch, stub)
    monkeypatch.setattr(
        cli_mod, "_load_cfg", lambda: _cfg(cli_delegate_sandbox=False)
    )

    seen: dict[str, Any] = {}

    class _SpyAdapter:
        def __init__(self, *, cfg, sandbox_run=None):
            seen["sandbox_run"] = sandbox_run

        def run(self, task, *, cwd, timeout_s):
            return DelegateResult("done", 0, "", "", sandboxed=False)

    monkeypatch.setattr(
        "athena.delegate.adapter.DelegateAdapter", _SpyAdapter
    )

    delegate_to_cli(task="t", repo_path=str(_make_repo(tmp_path)))
    assert seen["sandbox_run"] is None


# ---------------------------------------------------------------------------
# Untrusted output surfaced, not applied
# ---------------------------------------------------------------------------


def test_untrusted_output_surfaced_not_applied(tmp_path: Path, monkeypatch):
    """Even when the delegate succeeds, the tool returns the
    diff for review — it doesn't apply anything to the main
    tree. We verify the response has diff + next_step but no
    "applied" / "merged" / "committed-to-main" signal."""
    stub = _GitStub()
    _patch_git(monkeypatch, stub)
    monkeypatch.setattr(cli_mod, "_load_cfg", lambda: _cfg())
    monkeypatch.setattr(
        "athena.delegate.adapter.DelegateAdapter",
        lambda **kw: SimpleNamespace(
            run=lambda task, cwd, timeout_s: DelegateResult(
                "done", 0, "ok", "", False
            )
        ),
    )

    out = delegate_to_cli(task="x", repo_path=str(_make_repo(tmp_path)))
    payload = json.loads(out)
    # The diff is present and the next_step is the review prompt;
    # NO field claims the change is merged.
    assert "diff" in payload
    assert payload["next_step"]
    assert payload["status"] not in ("merged", "applied")
    # And no main-tree-mutation git ops fired.
    forbidden = {"merge", "push", "commit", "rebase", "checkout", "reset"}
    for argv in stub.calls:
        assert argv[1] not in forbidden


# ---------------------------------------------------------------------------
# Worktree prep failure → error, no adapter invocation
# ---------------------------------------------------------------------------


def test_worktree_prep_failure_surfaces_as_error(tmp_path: Path, monkeypatch):
    """A git worktree add failure → status=error with the
    underlying message, and the adapter is NEVER invoked
    (nothing to delegate to without a worktree)."""
    stub = _GitStub()
    # Make worktree add fail.
    def _fail_first(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, "", "fatal: ref bogus")

    _patch_git(monkeypatch, stub)
    # Override only the worktree-add call.
    monkeypatch.setattr(
        cli_mod,
        "subprocess",
        SimpleNamespace(
            run=_fail_first,
            CompletedProcess=subprocess.CompletedProcess,
            TimeoutExpired=subprocess.TimeoutExpired,
        ),
    )
    monkeypatch.setattr(cli_mod, "_load_cfg", lambda: _cfg())

    adapter_called = {"n": 0}

    class _ShouldNotRun:
        def __init__(self, **kw):
            adapter_called["n"] += 1

        def run(self, task, *, cwd, timeout_s):
            raise AssertionError("adapter must not run if worktree prep failed")

    monkeypatch.setattr(
        "athena.delegate.adapter.DelegateAdapter", _ShouldNotRun
    )

    out = delegate_to_cli(
        task="x", repo_path=str(_make_repo(tmp_path)), base_ref="bogus"
    )
    payload = json.loads(out)
    assert payload["status"] == "error"
    assert "bogus" in payload["reason"]
    assert adapter_called["n"] == 0
