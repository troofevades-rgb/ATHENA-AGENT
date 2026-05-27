"""Workspace path sandboxing for filesystem operations.

Every path passed to ``athena/tools/file_ops.py`` is validated through
``validate_path``. Paths inside the workspace are allowed without
prompt. Paths outside the workspace trigger the active approval
callback. A small allowlist (athena's own state directory, /tmp
scratch dirs the agent created) bypasses the prompt.

Absolute-deny patterns (process memory, kernel memory, EFI vars,
raw block devices) are refused regardless of approval.

Usage::

    from athena.safety.path_security import validate_path, allow_external

    path = validate_path(user_supplied_path, intent="read")
    # ... safe to read

    with allow_external():
        path = validate_path("/tmp/test-fixture", intent="write")

The workspace is set at agent init via ``set_workspace``. Tests
override via the autouse ``_path_security_workspace`` fixture in
``tests/conftest.py``.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

from .approval_callback import get_approval_callback

logger = logging.getLogger(__name__)


class PathSecurityDenied(PermissionError):
    """Raised when a path operation is refused.

    Either by absolute-deny pattern match or by approval-callback
    rejection.
    """


# MSYS/Git-Bash/Cygwin/WSL expose Windows drives at ``/c/...``, ``/d/...``,
# etc. The model's bash-trained instincts produce these paths constantly,
# but pathlib treats them as drive-less anchored paths and joining them
# with a Windows workspace produces ``C:\c\Users\...`` (the leading ``/``
# replaces the workspace's path while keeping the workspace's drive). That
# directory doesn't exist, so every Read/Edit fails until the model gives
# up and falls back to Bash. Normalize before resolution.
_MSYS_DRIVE_RX = re.compile(r"^/([a-zA-Z])(/.*)?$")


def normalize_msys_path(raw: str | Path) -> str | Path:
    """Convert ``/c/foo`` to ``C:/foo`` on Windows; passthrough elsewhere.

    Defensive on non-string inputs: returns the value unchanged when it
    doesn't match the MSYS shape so callers don't have to type-check.
    """
    if sys.platform != "win32":
        return raw
    s = str(raw)
    m = _MSYS_DRIVE_RX.match(s)
    if not m:
        return raw
    drive = m.group(1).upper()
    rest = m.group(2) or "/"
    return f"{drive}:{rest}"


_workspace: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "athena_path_security_workspace", default=None
)


def set_workspace(path: Path | str) -> None:
    """Set the workspace root for this context.

    Called once at agent init (and again per fork). The change
    persists for the current contextvar context.
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"workspace must be an existing directory: {resolved}")
    _workspace.set(resolved)


def get_workspace() -> Path:
    """Return the current workspace; defaults to cwd if unset."""
    ws = _workspace.get()
    if ws is None:
        return Path.cwd().resolve()
    return ws


# Paths that are always allowed without an approval prompt, even when
# outside the workspace. Tilde expands to ``Path.home()``. The literal
# ``*`` segment matches one path component (used for macOS TMPDIR's
# ``/var/folders/<two-char>/<long>/T/`` shape).
_ALWAYS_ALLOWED_PREFIXES: tuple[str, ...] = (
    "~/.athena",
    "~/.config/athena",
    "/tmp/athena-",
    "/var/folders/*/*/T/athena-",
)


# Paths that are always denied, even with foreground approval. These
# represent operations that can damage the host irrespective of user
# intent (process memory, kernel memory, raw block devices, firmware
# variables, Windows raw-device paths).
_ABSOLUTE_DENY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/proc/\d+/mem(/|$)"),
    re.compile(r"^/proc/kcore(/|$)"),
    re.compile(r"^/dev/(mem|kmem|port)(/|$)"),
    re.compile(r"^/dev/sd[a-z]\d*$"),
    re.compile(r"^/dev/nvme\d+n\d+(p\d+)?$"),
    re.compile(r"^/sys/firmware/efi/efivars(/|$)"),
    re.compile(r"^\\\\\.\\PHYSICALDRIVE\d+$", re.IGNORECASE),
    re.compile(r"^\\\\\.\\Volume\{.*\}$", re.IGNORECASE),
)


_allow_external_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "athena_path_security_allow_external_depth", default=0
)


@contextlib.contextmanager
def allow_external() -> Iterator[None]:
    """Suppress the approval prompt for outside-workspace paths.

    Used by test fixtures and by foreground tool implementations
    when the user explicitly supplied an absolute path.

    Does NOT bypass the absolute-deny patterns; process memory,
    kernel memory, and firmware paths are still refused.
    """
    token = _allow_external_depth.set(_allow_external_depth.get() + 1)
    try:
        yield
    finally:
        _allow_external_depth.reset(token)


def _is_inside_workspace(p: Path, workspace: Path) -> bool:
    try:
        return p.is_relative_to(workspace)
    except AttributeError:
        try:
            p.relative_to(workspace)
            return True
        except ValueError:
            return False


def _expanded_prefix(prefix: str, home: Path) -> str:
    return prefix.replace("~", str(home))


def _matches_glob_prefix(s: str, pattern: str) -> bool:
    """Match ``s`` against a prefix pattern that may contain '*' segments.

    Each '*' matches exactly one path component (no slashes). Used
    for the ``/var/folders/*/*/T/athena-`` macOS-TMPDIR shape.
    """
    if "*" not in pattern:
        return s.startswith(pattern)
    parts = pattern.split("*")
    # Anchored at the start.
    if not s.startswith(parts[0]):
        return False
    cursor = len(parts[0])
    for piece in parts[1:-1]:
        # The wildcard before ``piece`` consumes one path component.
        slash = s.find("/", cursor)
        if slash == -1:
            return False
        cursor = slash + 1
        if not s.startswith(piece, cursor):
            return False
        cursor += len(piece)
    # Final segment: '*' must consume one component before the suffix.
    tail = parts[-1]
    slash = s.find("/", cursor)
    if slash == -1:
        return False
    cursor = slash + 1
    return s.startswith(tail, cursor)


def _is_always_allowed(p: Path) -> bool:
    home = Path.home().as_posix()
    s = p.as_posix()
    for pattern in _ALWAYS_ALLOWED_PREFIXES:
        expanded = pattern.replace("~", home)
        if _matches_glob_prefix(s, expanded):
            return True
    return False


def _matches_absolute_deny(p: Path) -> bool:
    """Match against POSIX-shaped patterns and Windows raw-device strings.

    POSIX patterns are matched on ``as_posix()`` of the resolved path so
    Windows paths like ``C:/proc/1/mem`` don't accidentally pass through
    just because they have a drive letter prefix.
    """
    posix = p.as_posix()
    raw = str(p)
    for pat in _ABSOLUTE_DENY_PATTERNS:
        if pat.match(posix) or pat.match(raw):
            return True
        # POSIX-anchored patterns won't match if Windows prepended a
        # drive letter; strip a leading "<X>:" and re-test.
        if len(posix) >= 2 and posix[1] == ":":
            if pat.match(posix[2:]):
                return True
    return False


def audit_append(*, kind: str, payload: dict[str, Any]) -> None:
    """Record a policy event.

    A thin shim over ``logger.warning`` with a structured prefix so the
    event is grep-able. Tests monkeypatch this name to capture calls.
    """
    logger.warning(
        "path_security %s %s",
        kind,
        json.dumps(payload, separators=(",", ":")),
    )


def validate_path(
    raw: Path | str,
    *,
    intent: Literal["read", "write"],
    workspace: Path | None = None,
) -> Path:
    """Validate that ``raw`` is a safe path to operate on.

    Returns the resolved Path on success. Raises ``PathSecurityDenied``
    on refusal.

    Resolution order:
      1. Resolve ``raw`` (follows symlinks). ``strict=False`` so the
         caller can create new files.
      2. If the resolved path matches an absolute-deny pattern, refuse
         (no approval override).
      3. If the resolved path is inside the workspace, allow.
      4. If the resolved path matches an always-allowed prefix, allow.
      5. If ``allow_external()`` is active, allow.
      6. Otherwise, prompt via the active approval callback. If the
         callback returns anything other than "allow", raise
         PathSecurityDenied. If it returns "allow", record the
         approval via ``audit_append`` and allow.
    """
    ws = (workspace or get_workspace()).resolve()
    resolved = Path(normalize_msys_path(raw)).expanduser().resolve()

    if _matches_absolute_deny(resolved):
        logger.warning("path_security: absolute deny on %s", resolved)
        raise PathSecurityDenied(
            f"Refusing {intent} on {resolved}: matches absolute-deny pattern "
            "(process memory, kernel memory, firmware, or raw block device). "
            "This refusal cannot be overridden by approval."
        )

    if _is_inside_workspace(resolved, ws):
        return resolved

    if _is_always_allowed(resolved):
        return resolved

    if _allow_external_depth.get() > 0:
        return resolved

    callback = get_approval_callback()
    args = {
        "intent": intent,
        "path": str(resolved),
        "workspace": str(ws),
    }
    decision = callback("path_security", args)
    if decision != "allow":
        raise PathSecurityDenied(
            f"User denied outside-workspace {intent} on {resolved} (workspace={ws})"
        )

    audit_append(
        kind="path_security_approval",
        payload={
            "intent": intent,
            "path": str(resolved),
            "workspace": str(ws),
        },
    )
    return resolved
