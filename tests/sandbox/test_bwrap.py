"""Tests for athena.sandbox.bwrap (T5-02R.2).

Pure-function tests; no subprocess fires. The argv build is
deterministic — assert on the shape of the produced list.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.sandbox.bwrap import (
    build_bwrap_command,
    explain_unavailable,
    is_bwrap_available,
)


def _arg_pairs(argv: list[str], flag: str) -> list[tuple[str, str]]:
    """Collect every ``[flag, A, B]`` triple from ``argv`` as
    ``[(A, B), ...]``."""
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(argv):
        if argv[i] == flag and i + 2 < len(argv):
            out.append((argv[i + 1], argv[i + 2]))
            i += 3
            continue
        i += 1
    return out


# ---------------------------------------------------------------------------
# Wrapping shape
# ---------------------------------------------------------------------------


def test_build_wraps_inner_command(tmp_path: Path) -> None:
    inner = ["/bin/bash", "-c", "echo hi"]
    argv = build_bwrap_command(inner, workspace=tmp_path)
    assert argv[0] == "bwrap"
    # Inner argv appears after the `--` sentinel verbatim.
    sentinel = argv.index("--")
    assert argv[sentinel + 1 :] == inner


def test_first_element_is_bwrap_path_default(tmp_path: Path) -> None:
    assert build_bwrap_command([":"], workspace=tmp_path)[0] == "bwrap"


def test_bwrap_path_override(tmp_path: Path) -> None:
    """Tests inject a custom bwrap binary path to keep argv
    construction hermetic on hosts without bwrap installed."""
    argv = build_bwrap_command([":"], workspace=tmp_path, bwrap_path="/opt/test/bwrap")
    assert argv[0] == "/opt/test/bwrap"


# ---------------------------------------------------------------------------
# Network: default off, opt-in on
# ---------------------------------------------------------------------------


def test_default_no_network(tmp_path: Path) -> None:
    argv = build_bwrap_command([":"], workspace=tmp_path)
    assert "--unshare-net" in argv


def test_network_toggle_drops_unshare(tmp_path: Path) -> None:
    argv = build_bwrap_command([":"], workspace=tmp_path, allow_network=True)
    assert "--unshare-net" not in argv


# ---------------------------------------------------------------------------
# Filesystem bindings
# ---------------------------------------------------------------------------


def test_workspace_bound_writable(tmp_path: Path) -> None:
    argv = build_bwrap_command([":"], workspace=tmp_path)
    binds = _arg_pairs(argv, "--bind")
    # The workspace appears as a (src, dst) pair where src == dst.
    ws = str(tmp_path.resolve())
    assert (ws, ws) in binds


def test_root_is_ro_bind(tmp_path: Path) -> None:
    argv = build_bwrap_command([":"], workspace=tmp_path)
    ro_binds = _arg_pairs(argv, "--ro-bind")
    assert ("/", "/") in ro_binds


def test_writable_paths_bound_in_addition_to_workspace(tmp_path: Path) -> None:
    extra = tmp_path / "extra"
    extra.mkdir()
    argv = build_bwrap_command(
        [":"],
        workspace=tmp_path,
        writable_paths=[extra],
    )
    binds = _arg_pairs(argv, "--bind")
    ws = str(tmp_path.resolve())
    assert (ws, ws) in binds
    assert (str(extra.resolve()), str(extra.resolve())) in binds


def test_writable_paths_dedupes_workspace(tmp_path: Path) -> None:
    """Passing the workspace explicitly as a writable path
    doesn't double-bind it."""
    argv = build_bwrap_command([":"], workspace=tmp_path, writable_paths=[tmp_path])
    binds = _arg_pairs(argv, "--bind")
    ws = str(tmp_path.resolve())
    assert binds.count((ws, ws)) == 1


def test_proc_dev_tmp_overlays(tmp_path: Path) -> None:
    argv = build_bwrap_command([":"], workspace=tmp_path)
    # bwrap's own special-mount flags.
    assert "--proc" in argv and argv[argv.index("--proc") + 1] == "/proc"
    assert "--dev" in argv and argv[argv.index("--dev") + 1] == "/dev"
    assert "--tmpfs" in argv and argv[argv.index("--tmpfs") + 1] == "/tmp"


# ---------------------------------------------------------------------------
# Namespace + lifetime
# ---------------------------------------------------------------------------


def test_namespace_flags(tmp_path: Path) -> None:
    argv = build_bwrap_command([":"], workspace=tmp_path)
    for flag in (
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup",
    ):
        assert flag in argv, flag


def test_die_with_parent(tmp_path: Path) -> None:
    """Ensures the sandboxed child dies if athena exits — important
    because the streaming code in tools/shell.py expects to be able
    to kill the proc on timeout."""
    argv = build_bwrap_command([":"], workspace=tmp_path)
    assert "--die-with-parent" in argv


def test_cap_drop_all(tmp_path: Path) -> None:
    argv = build_bwrap_command([":"], workspace=tmp_path)
    assert "--cap-drop" in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def test_home_is_workspace(tmp_path: Path) -> None:
    argv = build_bwrap_command([":"], workspace=tmp_path)
    setenvs = _arg_pairs(argv, "--setenv")
    ws = str(tmp_path.resolve())
    assert ("HOME", ws) in setenvs


def test_chdir_workspace(tmp_path: Path) -> None:
    argv = build_bwrap_command([":"], workspace=tmp_path)
    assert "--chdir" in argv
    assert argv[argv.index("--chdir") + 1] == str(tmp_path.resolve())


# ---------------------------------------------------------------------------
# Availability detection
# ---------------------------------------------------------------------------


def test_unavailable_on_non_linux(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    assert is_bwrap_available() is False


def test_unavailable_when_not_on_path(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert is_bwrap_available() is False


def test_available_when_linux_and_on_path(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/bwrap")
    assert is_bwrap_available() is True


# ---------------------------------------------------------------------------
# Error messaging
# ---------------------------------------------------------------------------


def test_explain_unavailable_non_linux(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    msg = explain_unavailable()
    assert "Linux-only" in msg


def test_explain_unavailable_missing_bwrap(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    msg = explain_unavailable()
    assert "bubblewrap" in msg.lower()


def test_explain_when_available_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/bwrap")
    assert explain_unavailable() == ""
