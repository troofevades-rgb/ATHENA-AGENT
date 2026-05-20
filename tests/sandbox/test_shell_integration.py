"""Integration tests for the sandbox wrap of _spawn (T5-02R.3).

The shell module's ``_spawn`` is the single wrap point. These
tests stub ``subprocess.Popen`` so they don't actually fire any
command — the assertion is on the argv athena hands to Popen.

The shell_policy denylist still runs before ``_spawn`` (inside
``Bash``); a denylist-blocked command never reaches the sandbox.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.tools import shell


class _StubPopen:
    """Minimal Popen-shape stub that records the argv passed to it."""

    last_call: dict | None = None

    def __init__(self, *args, **kwargs):
        _StubPopen.last_call = {"args": args, "kwargs": kwargs}
        # The shell tool's streaming code reads from .stdout in a
        # while loop; an empty iterable + a poll() returning 0 makes
        # the loop terminate immediately. Plus we provide kill/wait.
        self.stdout = iter([])
        self.returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        return None


@pytest.fixture(autouse=True)
def _clean_popen_state(monkeypatch):
    """Reset the recorded Popen call before AND after each test."""
    _StubPopen.last_call = None
    monkeypatch.setattr(shell.subprocess, "Popen", _StubPopen)
    yield
    _StubPopen.last_call = None


def _set_cfg(monkeypatch, **overrides) -> None:
    """Install a cfg-shaped SimpleNamespace via load_config patching.

    Defaults reflect a normal install: sandbox off, sane policy."""
    cfg = SimpleNamespace(
        bash_extra_denylist=[],
        bash_allowlist=[],
        safety={},
        sandbox_enabled=False,
        sandbox_backend="bwrap",
        sandbox_allow_network=False,
        sandbox_writable_paths=[],
        sandbox_fallback="warn",
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    monkeypatch.setattr("athena.config.load_config", lambda: cfg)


def _set_workspace(tmp_path: Path) -> None:
    """Pin the file_ops workspace so Popen's cwd is deterministic."""
    from athena.tools import file_ops

    file_ops.set_workspace(tmp_path, max_read=1_000_000)


# ---------------------------------------------------------------------------
# Sandbox-off: byte-identical to today
# ---------------------------------------------------------------------------


def test_disabled_runs_unwrapped(monkeypatch, tmp_path: Path) -> None:
    _set_cfg(monkeypatch, sandbox_enabled=False)
    _set_workspace(tmp_path)

    shell._spawn("echo hello")
    call = _StubPopen.last_call
    assert call is not None
    argv = call["args"][0]
    # argv is a string (POSIX shell=True path) or a list (Windows
    # bash path) — but NEVER a bwrap-prefixed list.
    if isinstance(argv, list):
        assert argv[0] != "bwrap"
    else:
        assert "bwrap" not in argv


# ---------------------------------------------------------------------------
# Sandbox-on, bwrap available: command gets rewritten
# ---------------------------------------------------------------------------


def test_sandboxed_command_is_bwrap_wrapped(monkeypatch, tmp_path: Path) -> None:
    _set_cfg(monkeypatch, sandbox_enabled=True)
    _set_workspace(tmp_path)
    monkeypatch.setattr("athena.sandbox.bwrap.is_bwrap_available", lambda: True)

    shell._spawn("echo hello")
    call = _StubPopen.last_call
    assert call is not None
    argv = call["args"][0]
    assert isinstance(argv, list)
    assert argv[0] == "bwrap"
    # The inner argv lands after the `--` sentinel.
    sentinel = argv.index("--")
    inner = argv[sentinel + 1 :]
    assert inner[-2:] == ["-c", "echo hello"]
    # shell=False on the bwrap path.
    assert call["kwargs"]["shell"] is False


def test_sandboxed_workspace_bound(monkeypatch, tmp_path: Path) -> None:
    _set_cfg(monkeypatch, sandbox_enabled=True)
    _set_workspace(tmp_path)
    monkeypatch.setattr("athena.sandbox.bwrap.is_bwrap_available", lambda: True)

    shell._spawn("pwd")
    argv = _StubPopen.last_call["args"][0]
    ws = str(tmp_path.resolve())
    # --bind <ws> <ws> appears in the bwrap argv.
    binds = [(argv[i + 1], argv[i + 2]) for i in range(len(argv) - 2) if argv[i] == "--bind"]
    assert (ws, ws) in binds


def test_sandboxed_allow_network_flag(monkeypatch, tmp_path: Path) -> None:
    _set_cfg(monkeypatch, sandbox_enabled=True, sandbox_allow_network=True)
    _set_workspace(tmp_path)
    monkeypatch.setattr("athena.sandbox.bwrap.is_bwrap_available", lambda: True)

    shell._spawn("curl example.com")
    argv = _StubPopen.last_call["args"][0]
    # Network allowed → --unshare-net is NOT in the bwrap argv.
    assert "--unshare-net" not in argv


def test_sandboxed_writable_paths_extra(monkeypatch, tmp_path: Path) -> None:
    extra = tmp_path / "cache"
    extra.mkdir()
    _set_cfg(
        monkeypatch,
        sandbox_enabled=True,
        sandbox_writable_paths=[str(extra)],
    )
    _set_workspace(tmp_path)
    monkeypatch.setattr("athena.sandbox.bwrap.is_bwrap_available", lambda: True)

    shell._spawn("ls")
    argv = _StubPopen.last_call["args"][0]
    binds = [(argv[i + 1], argv[i + 2]) for i in range(len(argv) - 2) if argv[i] == "--bind"]
    assert (str(extra.resolve()), str(extra.resolve())) in binds


# ---------------------------------------------------------------------------
# bwrap unavailable: fallback semantics
# ---------------------------------------------------------------------------


def test_fallback_warn_runs_unsandboxed(monkeypatch, tmp_path: Path) -> None:
    """When bwrap is unavailable AND sandbox_fallback="warn", the
    command runs unsandboxed (with a logged warning that we don't
    assert on directly — it's a logger.warning call)."""
    _set_cfg(monkeypatch, sandbox_enabled=True, sandbox_fallback="warn")
    _set_workspace(tmp_path)
    monkeypatch.setattr("athena.sandbox.bwrap.is_bwrap_available", lambda: False)

    shell._spawn("echo fallback")
    call = _StubPopen.last_call
    argv = call["args"][0]
    # No bwrap; the existing un-sandboxed path runs.
    if isinstance(argv, list):
        assert argv[0] != "bwrap"
    else:
        assert "bwrap" not in argv


def test_fallback_error_refuses(monkeypatch, tmp_path: Path) -> None:
    """When sandbox_fallback="error", _spawn raises so the caller
    can surface a BLOCKED message instead of running unsandboxed."""
    _set_cfg(monkeypatch, sandbox_enabled=True, sandbox_fallback="error")
    _set_workspace(tmp_path)
    monkeypatch.setattr("athena.sandbox.bwrap.is_bwrap_available", lambda: False)

    with pytest.raises(shell.SandboxUnavailableError):
        shell._spawn("echo nope")


def test_bash_tool_surfaces_blocked_sandbox(monkeypatch, tmp_path: Path) -> None:
    """End-to-end: a user invoking the Bash tool with the sandbox
    required-but-unavailable sees a BLOCKED message in the
    response, no Popen ever fires."""
    _set_cfg(monkeypatch, sandbox_enabled=True, sandbox_fallback="error")
    _set_workspace(tmp_path)
    monkeypatch.setattr("athena.sandbox.bwrap.is_bwrap_available", lambda: False)

    out = shell.Bash(command="echo hi", timeout=10)
    assert out.startswith("BLOCKED by sandbox:")
    # Popen never spawned.
    assert _StubPopen.last_call is None


# ---------------------------------------------------------------------------
# Policy floor still runs first
# ---------------------------------------------------------------------------


def test_denylist_still_runs_first(monkeypatch, tmp_path: Path) -> None:
    """When the denylist blocks a command, _spawn is never reached
    — sandbox config is irrelevant."""
    _set_cfg(monkeypatch, sandbox_enabled=True)
    _set_workspace(tmp_path)
    monkeypatch.setattr("athena.sandbox.bwrap.is_bwrap_available", lambda: True)

    # `rm -rf /` is in DEFAULT_DENYLIST; the Bash tool short-circuits.
    out = shell.Bash(command="rm -rf /", timeout=10)
    assert out.startswith("BLOCKED by shell policy:")
    assert _StubPopen.last_call is None


# ---------------------------------------------------------------------------
# Timeout + streaming pass through unchanged
# ---------------------------------------------------------------------------


def test_timeout_preserved(monkeypatch, tmp_path: Path) -> None:
    """Bash() clamps timeout to [1, 600] and passes it to the
    streamer. The sandbox doesn't change this — _spawn returns
    a Popen-shape object either way and the same _stream_* code
    drives it."""
    _set_cfg(monkeypatch, sandbox_enabled=True)
    _set_workspace(tmp_path)
    monkeypatch.setattr("athena.sandbox.bwrap.is_bwrap_available", lambda: True)

    captured: dict = {}

    def _fake_streamer(proc, timeout):
        captured["timeout"] = timeout
        return ""

    monkeypatch.setattr(shell, "_stream_posix", _fake_streamer)
    monkeypatch.setattr(shell, "_stream_windows", _fake_streamer)

    shell.Bash(command="echo hi", timeout=42)
    assert captured["timeout"] == 42


def test_timeout_clamped(monkeypatch, tmp_path: Path) -> None:
    """Timeout > 600 clamps to 600, < 1 clamps to 1 — same as today.
    Sandbox-on or off, the clamp lives in Bash()."""
    _set_cfg(monkeypatch, sandbox_enabled=True)
    _set_workspace(tmp_path)
    monkeypatch.setattr("athena.sandbox.bwrap.is_bwrap_available", lambda: True)

    captured: dict = {}

    def _fake_streamer(proc, timeout):
        captured.setdefault("timeouts", []).append(timeout)
        return ""

    monkeypatch.setattr(shell, "_stream_posix", _fake_streamer)
    monkeypatch.setattr(shell, "_stream_windows", _fake_streamer)

    shell.Bash(command="a", timeout=9999)
    # Negative values bypass the `or 120` short-circuit then clamp
    # to the lower bound of 1.
    shell.Bash(command="b", timeout=-5)
    assert captured["timeouts"] == [600, 1]
