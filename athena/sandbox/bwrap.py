"""Bubblewrap command-rewriting backend (T5-02R.2).

Pure functions only — no I/O at import time, no spawning. The
caller (``athena.tools.shell._spawn``) decides whether to use
this; this module just produces the argv.

The wrapped shape:

  bwrap
    --die-with-parent
    --new-session
    --unshare-pid --unshare-ipc --unshare-uts --unshare-cgroup
    --unshare-net                            # default: no network
    --ro-bind / /
    --proc /proc
    --dev /dev
    --tmpfs /tmp
    --bind <workspace> <workspace>            # writable workspace
    --bind <p> <p> for p in sandbox_writable_paths
    --setenv HOME <workspace>
    --chdir <workspace>
    --
    <inner argv>

Read-only system + writable workspace is the safe default.
``sandbox_allow_network=True`` drops ``--unshare-net``.
``sandbox_writable_paths`` extends the bind set for users with
out-of-tree caches (``~/.cache``, ``/tmp/build-out``, etc.).

This module intentionally doesn't try to be a full container —
it's an OS-level "no escape from the workspace" jail layered on
top of athena's existing shell policy.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def is_bwrap_available() -> bool:
    """``True`` iff the host can sandbox today.

    Requires Linux (bwrap is Linux-only) AND ``bwrap`` on PATH.
    Both conditions checked at call time — the caller decides
    fallback semantics."""
    if sys.platform != "linux":
        return False
    return shutil.which("bwrap") is not None


def build_bwrap_command(
    inner_argv: list[str],
    *,
    workspace: str | Path,
    allow_network: bool = False,
    writable_paths: list[str | Path] | None = None,
    bwrap_path: str = "bwrap",
) -> list[str]:
    """Return the argv that runs ``inner_argv`` inside a bwrap jail.

    ``inner_argv`` is the command athena would have spawned
    directly (e.g. ``["/bin/bash", "-c", "ls"]`` or
    ``["/bin/sh", "-c", "..."]``). The result is the full argv to
    pass to ``subprocess.Popen`` with ``shell=False``.

    ``writable_paths`` extends the default workspace bind. Empty
    by default; the workspace alone is enough for most workflows.

    ``bwrap_path`` lets tests inject a stub binary path.
    """
    ws = str(Path(workspace).resolve())
    extra_writable = list(writable_paths or [])

    # bwrap argv. Each pair of options is grouped for readability;
    # bwrap doesn't care about order beyond the final `--`.
    cmd: list[str] = [
        bwrap_path,
        # Lifetime / signal forwarding
        "--die-with-parent",
        "--new-session",
        # Namespace isolation
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup",
        # Privilege drops
        "--cap-drop",
        "ALL",
        # Filesystem: read-only system root
        "--ro-bind",
        "/",
        "/",
        # /proc + /dev + /tmp need explicit overlay in a sandbox
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
    ]

    # Network namespace — the security default is no network.
    if not allow_network:
        cmd.append("--unshare-net")

    # Writable workspace bind (the canonical writable path)
    cmd.extend(["--bind", ws, ws])

    # Extra writable paths the user opted into
    seen: set[str] = {ws}
    for p in extra_writable:
        resolved = str(Path(p).expanduser().resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        cmd.extend(["--bind", resolved, resolved])

    # Pretend HOME is the workspace so tools that look there
    # (~/.cache, ~/.config, ssh-keyless) don't escape the bind set.
    cmd.extend(["--setenv", "HOME", ws])

    # Start the inner process in the workspace.
    cmd.extend(["--chdir", ws])

    # Sentinel separating bwrap options from the inner argv.
    cmd.append("--")

    # Inner command verbatim.
    cmd.extend(inner_argv)
    return cmd


def explain_unavailable() -> str:
    """User-facing one-liner describing why bwrap isn't usable
    on this host. Driven by the same checks as
    :func:`is_bwrap_available`."""
    if sys.platform != "linux":
        return (
            f"bubblewrap is Linux-only; current platform is "
            f"{sys.platform!r}. The sandbox can't run here — pass "
            "sandbox_enabled=false or set sandbox_fallback='warn' "
            "to keep working with the shell_policy denylist alone."
        )
    if shutil.which("bwrap") is None:
        return (
            "bubblewrap (bwrap) isn't on PATH. Install it "
            "(`apt install bubblewrap` / `dnf install bubblewrap` / "
            "`pacman -S bubblewrap`) or set sandbox_enabled=false."
        )
    return ""  # No problem detected
