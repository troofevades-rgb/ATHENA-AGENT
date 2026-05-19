"""Tests for athena.safety.path_security.

The project's approval callback signature is
``(tool_name: str, args: dict) -> "allow"|"deny"`` (not the
``(prompt) -> bool`` from the original design doc). Tests use the
project's actual signature.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from athena.safety.approval_callback import (
    reset_approval_callback,
    set_approval_callback,
)
from athena.safety.path_security import (
    PathSecurityDenied,
    allow_external,
    set_workspace,
    validate_path,
)


def _allow_cb(*_args: Any, **_kwargs: Any) -> str:
    return "allow"


def _deny_cb(*_args: Any, **_kwargs: Any) -> str:
    return "deny"


@pytest.fixture
def isolated_workspace(tmp_path: Path) -> Path:
    """Point path_security at tmp_path for this test."""
    set_workspace(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Workspace boundary
# ---------------------------------------------------------------------------


def test_inside_workspace_allowed(isolated_workspace: Path) -> None:
    target = isolated_workspace / "file.txt"
    target.write_text("hello")
    result = validate_path(target, intent="read")
    assert result == target.resolve()


def test_nested_inside_workspace_allowed(isolated_workspace: Path) -> None:
    nested = isolated_workspace / "a" / "b" / "c.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("hello")
    result = validate_path(nested, intent="read")
    assert result == nested.resolve()


def test_outside_workspace_denied_by_default(isolated_workspace: Path) -> None:
    outside = Path("/tmp/definitely-not-in-workspace.txt").resolve()
    token = set_approval_callback(_deny_cb)
    try:
        with pytest.raises(PathSecurityDenied):
            validate_path(outside, intent="read")
    finally:
        reset_approval_callback(token)


def test_outside_workspace_allowed_by_approval(isolated_workspace: Path) -> None:
    outside = Path("/tmp/some-other-test-file.txt").resolve()
    token = set_approval_callback(_allow_cb)
    try:
        result = validate_path(outside, intent="read")
        assert result == outside.resolve()
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------------------
# Symlink resolution
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="symlink creation often requires elevated privileges on Windows",
)
def test_symlink_outside_workspace_denied(isolated_workspace: Path) -> None:
    """A symlink inside the workspace pointing outside is denied."""
    target_outside = Path("/etc/hostname")
    if not target_outside.exists():
        pytest.skip("no /etc/hostname on this system")
    link = isolated_workspace / "innocent-looking-link"
    link.symlink_to(target_outside)
    token = set_approval_callback(_deny_cb)
    try:
        with pytest.raises(PathSecurityDenied):
            validate_path(link, intent="read")
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------------------
# Absolute-deny patterns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "p",
    [
        "/proc/1/mem",
        "/proc/kcore",
        "/dev/mem",
        "/dev/kmem",
        "/dev/sda1",
        "/sys/firmware/efi/efivars/anything-here",
    ],
)
def test_absolute_deny_patterns(isolated_workspace: Path, p: str) -> None:
    """Even an approve-everything callback can't bypass these."""
    token = set_approval_callback(_allow_cb)
    try:
        with pytest.raises(PathSecurityDenied, match="absolute-deny"):
            validate_path(p, intent="read")
    finally:
        reset_approval_callback(token)


def test_absolute_deny_not_overridden_by_allow_external(
    isolated_workspace: Path,
) -> None:
    with allow_external():
        with pytest.raises(PathSecurityDenied, match="absolute-deny"):
            validate_path("/proc/1/mem", intent="read")


# ---------------------------------------------------------------------------
# Always-allowed prefixes
# ---------------------------------------------------------------------------


def test_dot_athena_always_allowed(isolated_workspace: Path) -> None:
    home_athena = Path.home() / ".athena"
    candidate = home_athena / "credentials.json"
    token = set_approval_callback(_deny_cb)
    try:
        result = validate_path(candidate, intent="read")
        assert result == candidate.resolve()
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------------------
# allow_external context manager
# ---------------------------------------------------------------------------


def test_allow_external_bypasses_approval(isolated_workspace: Path) -> None:
    outside = Path("/tmp/external-test-file.txt").resolve()
    token = set_approval_callback(_deny_cb)
    try:
        with allow_external():
            result = validate_path(outside, intent="write")
            assert result == outside.resolve()
    finally:
        reset_approval_callback(token)


def test_allow_external_does_not_persist(isolated_workspace: Path) -> None:
    outside = Path("/tmp/external-test-file-2.txt").resolve()
    token = set_approval_callback(_deny_cb)
    try:
        with allow_external():
            validate_path(outside, intent="read")
        with pytest.raises(PathSecurityDenied):
            validate_path(outside, intent="read")
    finally:
        reset_approval_callback(token)


def test_allow_external_nests_correctly(isolated_workspace: Path) -> None:
    outside = Path("/tmp/external-test-file-3.txt").resolve()
    token = set_approval_callback(_deny_cb)
    try:
        with allow_external():
            with allow_external():
                validate_path(outside, intent="read")
            validate_path(outside, intent="read")
        with pytest.raises(PathSecurityDenied):
            validate_path(outside, intent="read")
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


def test_approved_outside_write_records_audit(
    isolated_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = Path("/tmp/audit-test.txt").resolve()
    audit_calls: list[dict[str, Any]] = []

    def fake_append(*, kind: str, payload: dict[str, Any]) -> None:
        audit_calls.append({"kind": kind, "payload": payload})

    monkeypatch.setattr("athena.safety.path_security.audit_append", fake_append)

    token = set_approval_callback(_allow_cb)
    try:
        validate_path(outside, intent="write")
    finally:
        reset_approval_callback(token)

    assert len(audit_calls) == 1
    assert audit_calls[0]["kind"] == "path_security_approval"
    assert audit_calls[0]["payload"]["intent"] == "write"
    assert audit_calls[0]["payload"]["path"] == str(outside.resolve())


# ---------------------------------------------------------------------------
# Integration with file_ops
# ---------------------------------------------------------------------------


def test_file_ops_read_inside_workspace(isolated_workspace: Path) -> None:
    from athena.tools import file_ops

    file_ops.set_workspace(isolated_workspace)
    f = isolated_workspace / "hello.txt"
    f.write_text("contents")
    result = file_ops.Read(str(f))
    assert "contents" in result


def test_file_ops_read_outside_denied(isolated_workspace: Path) -> None:
    from athena.tools import file_ops

    file_ops.set_workspace(isolated_workspace)
    token = set_approval_callback(_deny_cb)
    try:
        with pytest.raises(PathSecurityDenied):
            file_ops.Read("/etc/passwd")
    finally:
        reset_approval_callback(token)


def test_file_ops_write_outside_denied(isolated_workspace: Path) -> None:
    from athena.tools import file_ops

    file_ops.set_workspace(isolated_workspace)
    token = set_approval_callback(_deny_cb)
    try:
        with pytest.raises(PathSecurityDenied):
            file_ops.Write("/tmp/should-not-write-T1-07.txt", "x")
    finally:
        reset_approval_callback(token)
