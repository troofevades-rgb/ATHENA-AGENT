"""Install / pin / rollback tests (T6-07.3).

Every subprocess call goes through ``apply._run`` — tests
monkeypatch that to a stub recorder so no real pip / git /
pipx invocation fires. The load-bearing properties:

  - The matching install method is called for each
    InstallMethod (pip → `python -m pip install --upgrade`,
    pipx → `pipx upgrade` or pinned install, git → fetch +
    checkout + pip install .)
  - EDITABLE refuses cleanly (never installs over a
    developer's working tree)
  - UNKNOWN refuses cleanly with a helpful message
  - record_prior + rollback round-trip the version string
  - --to <version> pins to exactly that version
  - NEVER hot-swaps the running process — no os.execv,
    sys.executable replacement, etc.; only install +
    "restart" message
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import athena.update.apply  # noqa: F401 — load submodule

apply_module = sys.modules["athena.update.apply"]
from athena.update.apply import (
    ApplyResult,
    install,
    read_prior,
    record_prior,
    rollback,
    state_path,
)
from athena.update.detect import InstallMethod


# ---------------------------------------------------------------------------
# Subprocess recorder
# ---------------------------------------------------------------------------


class _RunRecorder:
    """Records every ``_run`` call. Returns canned
    (returncode, stdout, stderr) per call from
    ``responses`` (or a default success)."""

    def __init__(self, responses: list[tuple[int, str, str]] | None = None):
        self.calls: list[list[str]] = []
        self.responses = list(responses or [])

    def __call__(self, argv: list[str], *, timeout: float = 300.0):
        self.calls.append(list(argv))
        if self.responses:
            return self.responses.pop(0)
        return 0, "ok", ""


def _which_yes(monkeypatch):
    """Make shutil.which return a non-None value for any
    command, so the pre-flight pipx/git checks don't refuse
    in tests."""
    monkeypatch.setattr(apply_module.shutil, "which", lambda _cmd: "/usr/bin/" + _cmd)


def _cfg(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(update_state_path=str(tmp_path / "update_state.json"))


# ---------------------------------------------------------------------------
# install — method dispatch
# ---------------------------------------------------------------------------


def test_install_via_pip(monkeypatch, tmp_path: Path):
    """PIP installs via `python -m pip install --upgrade`."""
    recorder = _RunRecorder()
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    result = install(InstallMethod.PIP, version="0.3.0")
    assert result.status == "done"
    assert result.method == "pip"
    assert result.version_installed == "0.3.0"
    assert "restart athena" in result.message

    # Exactly one subprocess call: `python -m pip install
    # --upgrade athena-coder==0.3.0`.
    assert len(recorder.calls) == 1
    argv = recorder.calls[0]
    assert argv[0] == sys.executable
    assert argv[1:5] == ["-m", "pip", "install", "--upgrade"]
    assert "athena-coder==0.3.0" in argv


def test_install_pip_latest_unpinned(monkeypatch, tmp_path: Path):
    """version=None → installs latest (no ==X.Y.Z suffix)."""
    recorder = _RunRecorder()
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    install(InstallMethod.PIP, version=None)
    argv = recorder.calls[0]
    assert "athena-coder" in argv
    # No version pin.
    assert not any("==" in arg for arg in argv)


def test_install_pipx_upgrade(monkeypatch, tmp_path: Path):
    """PIPX with no version → `pipx upgrade <pkg>`."""
    recorder = _RunRecorder()
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    install(InstallMethod.PIPX, version=None)
    assert recorder.calls[0] == ["pipx", "upgrade", "athena-coder"]


def test_install_pipx_pinned_uses_force(monkeypatch, tmp_path: Path):
    """PIPX with a pinned version uses `pipx install
    pkg==version --force` (pipx upgrade doesn't pin)."""
    recorder = _RunRecorder()
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    install(InstallMethod.PIPX, version="0.2.5")
    assert recorder.calls[0] == [
        "pipx", "install", "athena-coder==0.2.5", "--force"
    ]


def test_install_pipx_missing_returns_error(monkeypatch, tmp_path: Path):
    """pipx not on PATH → clean error message, no subprocess
    call fires."""
    monkeypatch.setattr(apply_module.shutil, "which", lambda _: None)
    recorder = _RunRecorder()
    monkeypatch.setattr(apply_module, "_run", recorder)

    result = install(InstallMethod.PIPX, version="0.3.0")
    assert result.status == "error"
    assert "pipx not on PATH" in result.message
    assert recorder.calls == []


def test_install_via_git_with_version(monkeypatch, tmp_path: Path):
    """GIT: fetch + checkout v<version> + pip install ."""
    recorder = _RunRecorder([(0, "", ""), (0, "", ""), (0, "", "")])
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    result = install(
        InstallMethod.GIT, version="0.3.0", repo_root=str(tmp_path)
    )
    assert result.status == "done"
    # Three calls: fetch, checkout, install.
    assert len(recorder.calls) == 3
    assert recorder.calls[0][:3] == ["git", "-C", str(tmp_path)]
    assert recorder.calls[0][3:] == ["fetch", "--tags"]
    assert recorder.calls[1][3:] == ["checkout", "v0.3.0"]
    # pip install . runs at the end.
    assert recorder.calls[2][0] == sys.executable
    assert recorder.calls[2][3:] == ["install", "."]


def test_install_via_git_falls_back_to_bare_version(monkeypatch, tmp_path: Path):
    """v<version> fails → tries bare <version>."""
    # checkout v0.3.0 fails (rc=1), checkout 0.3.0 succeeds, pip install ok.
    recorder = _RunRecorder(
        [
            (0, "", ""),           # fetch
            (1, "", "no v-tag"),   # checkout v0.3.0 fails
            (0, "", ""),           # checkout 0.3.0 succeeds
            (0, "", ""),           # pip install .
        ]
    )
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    result = install(
        InstallMethod.GIT, version="0.3.0", repo_root=str(tmp_path)
    )
    assert result.status == "done"
    # Both refs tried.
    checkout_refs = [c[4] for c in recorder.calls if "checkout" in c]
    assert checkout_refs == ["v0.3.0", "0.3.0"]


def test_install_via_git_unpinned_uses_ff_merge(monkeypatch, tmp_path: Path):
    """No version → fast-forward merge to origin/HEAD instead
    of a tag checkout."""
    recorder = _RunRecorder([(0, "", ""), (0, "", ""), (0, "", "")])
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    install(InstallMethod.GIT, version=None, repo_root=str(tmp_path))
    # Second call is the merge --ff-only.
    assert "merge" in recorder.calls[1]
    assert "--ff-only" in recorder.calls[1]


def test_install_via_git_no_git(monkeypatch, tmp_path: Path):
    """git missing from PATH → clean error, no subprocess
    calls fire."""
    monkeypatch.setattr(apply_module.shutil, "which", lambda _: None)
    recorder = _RunRecorder()
    monkeypatch.setattr(apply_module, "_run", recorder)

    result = install(InstallMethod.GIT, version="0.3.0", repo_root=".")
    assert result.status == "error"
    assert "git not on PATH" in result.message
    assert recorder.calls == []


def test_install_via_git_fetch_failure(monkeypatch, tmp_path: Path):
    """Failed fetch → error status, no further calls."""
    recorder = _RunRecorder([(1, "", "fatal: cannot fetch")])
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    result = install(InstallMethod.GIT, version="0.3.0", repo_root=".")
    assert result.status == "error"
    assert "fetch failed" in result.message
    # Only one call — we don't proceed past a fetch failure.
    assert len(recorder.calls) == 1


# ---------------------------------------------------------------------------
# EDITABLE refuses
# ---------------------------------------------------------------------------


def test_editable_warns_not_installs(monkeypatch):
    """EDITABLE refuses cleanly — never installs over a
    developer's working tree."""
    recorder = _RunRecorder()
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    result = install(InstallMethod.EDITABLE, version="0.5.0")
    assert result.status == "refused"
    assert "editable" in result.message.lower()
    assert "source checkout" in result.message
    # No subprocess call fired.
    assert recorder.calls == []


def test_unknown_refuses_with_help(monkeypatch):
    recorder = _RunRecorder()
    monkeypatch.setattr(apply_module, "_run", recorder)

    result = install(InstallMethod.UNKNOWN)
    assert result.status == "refused"
    # Help message names every supported method.
    assert "pip install" in result.message
    assert "pipx upgrade" in result.message
    assert "git pull" in result.message
    assert recorder.calls == []


# ---------------------------------------------------------------------------
# record_prior / rollback
# ---------------------------------------------------------------------------


def test_record_prior_writes_state_file(tmp_path: Path):
    cfg = _cfg(tmp_path)
    assert record_prior("0.2.0", cfg=cfg) is True
    payload = json.loads(state_path(cfg=cfg).read_text(encoding="utf-8"))
    assert payload["prior_version"] == "0.2.0"
    assert "recorded_at" in payload


def test_record_prior_empty_returns_false(tmp_path: Path):
    cfg = _cfg(tmp_path)
    assert record_prior("", cfg=cfg) is False
    assert not state_path(cfg=cfg).exists()


def test_read_prior_when_absent(tmp_path: Path):
    cfg = _cfg(tmp_path)
    assert read_prior(cfg=cfg) is None


def test_read_prior_round_trip(tmp_path: Path):
    cfg = _cfg(tmp_path)
    record_prior("0.4.2", cfg=cfg)
    assert read_prior(cfg=cfg) == "0.4.2"


def test_read_prior_handles_corrupt_file(tmp_path: Path):
    cfg = _cfg(tmp_path)
    state_path(cfg=cfg).parent.mkdir(parents=True, exist_ok=True)
    state_path(cfg=cfg).write_text("not valid json {{{", encoding="utf-8")
    assert read_prior(cfg=cfg) is None


def test_record_prior_then_rollback(monkeypatch, tmp_path: Path):
    """The headline round-trip: record a prior version then
    rollback installs it via the detected method."""
    cfg = _cfg(tmp_path)
    record_prior("0.1.5", cfg=cfg)

    # Force the detect() call inside rollback() to return PIP.
    # rollback() does `from .detect import detect` inside the
    # function — patch the module-level attribute via sys.modules.
    detect_mod = sys.modules["athena.update.detect"]
    monkeypatch.setattr(detect_mod, "detect", lambda pkg="athena-coder": InstallMethod.PIP)

    recorder = _RunRecorder()
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    result = rollback(cfg=cfg)
    assert result.status == "done"
    assert result.version_installed == "0.1.5"
    assert "rolled back to 0.1.5" in result.message
    # Pip installed exactly 0.1.5.
    argv = recorder.calls[0]
    assert "athena-coder==0.1.5" in argv


def test_rollback_with_no_prior_recorded(tmp_path: Path):
    cfg = _cfg(tmp_path)
    result = rollback(cfg=cfg)
    assert result.status == "refused"
    assert "no prior version" in result.message


# ---------------------------------------------------------------------------
# --to <version> pinning (via install)
# ---------------------------------------------------------------------------


def test_to_pins_version(monkeypatch, tmp_path: Path):
    """install(method, version="0.4.2") installs exactly that
    version — works for up- and down-graded targets."""
    recorder = _RunRecorder()
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    install(InstallMethod.PIP, version="0.4.2")
    argv = recorder.calls[0]
    assert "athena-coder==0.4.2" in argv


# ---------------------------------------------------------------------------
# Integrity / no-hot-swap invariants
# ---------------------------------------------------------------------------


def test_install_routes_through_pip(monkeypatch, tmp_path: Path):
    """Integrity verification: every install goes through pip
    (so pip's wheel-hash verification fires automatically).
    We assert the install command starts with `python -m pip`
    — no direct wheel download / urlopen path."""
    recorder = _RunRecorder()
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    install(InstallMethod.PIP, version="0.3.0")
    argv = recorder.calls[0]
    # `python -m pip` is the route — pip handles hash
    # verification against PyPI's recorded hashes.
    assert argv[0] == sys.executable
    assert argv[1:3] == ["-m", "pip"]


def test_install_does_not_exec_or_hot_swap(monkeypatch, tmp_path: Path):
    """No os.execv / os.execvp / sys.exit fires from the
    install path. The contract: install + advise restart,
    NEVER replace the running process. We monkeypatch the
    dangerous APIs to tripwires and verify they're not
    called."""
    import os

    exec_called = {"n": 0}

    def _tripwire(*a, **k):
        exec_called["n"] += 1
        raise AssertionError("hot-swap forbidden: install path called exec")

    monkeypatch.setattr(os, "execv", _tripwire, raising=False)
    monkeypatch.setattr(os, "execvp", _tripwire, raising=False)
    monkeypatch.setattr(os, "_exit", _tripwire, raising=False)

    recorder = _RunRecorder()
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    result = install(InstallMethod.PIP, version="0.3.0")
    assert result.status == "done"
    # The success message instead tells the user to restart.
    assert "restart" in result.message.lower()
    assert exec_called["n"] == 0


# ---------------------------------------------------------------------------
# Failure surfacing
# ---------------------------------------------------------------------------


def test_install_pip_failure_returns_error_with_stderr(monkeypatch):
    """Non-zero exit → error status carrying stdout + stderr."""
    recorder = _RunRecorder([(1, "some output", "ERROR: something broke")])
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    result = install(InstallMethod.PIP, version="0.3.0")
    assert result.status == "error"
    assert "ERROR: something broke" in result.stderr
    assert "pip install failed" in result.message


def test_install_handles_timeout(monkeypatch):
    """The _run wrapper returns code=124 on TimeoutExpired;
    install surfaces it as an error."""
    recorder = _RunRecorder([(124, "", "[update] command timed out after 300s")])
    monkeypatch.setattr(apply_module, "_run", recorder)
    _which_yes(monkeypatch)

    result = install(InstallMethod.PIP, version="0.3.0")
    assert result.status == "error"
    assert "timed out" in result.stderr
