"""Bash execution tool. Subject to the agent's confirmation gate
(unless the command matches the bash_allowlist or auto_approve_tools is set).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

from ..safety.shell_policy import DEFAULT_DENYLIST, ShellPolicy
from ..ui import console
from . import file_ops  # for workspace
from .registry import tool

# Windows drive-letter paths with backslash separators get mangled by
# Bash (Git Bash / MSYS) which treats backslash as an escape character.
# ``python C:\Users\foo\bar.py`` becomes ``python C:Usersfoobar.py``
# after bash unwraps the escapes. Detect drive-letter paths and rewrite
# to forward slashes — accepted by Python, Git, most Windows tools, and
# transparent to Bash.
#
# Anchored on word boundary + drive letter + colon + backslash so we
# don't rewrite escape sequences elsewhere in the command (``echo
# "line1\nline2"``, regex literals, etc.). The body stops at shell
# metacharacters so we don't slurp into the next argument.
_WIN_PATH_RX = re.compile(r"\b([A-Za-z]):\\([^\s'\"<>|;&]*)")


def _normalize_windows_paths(command: str) -> str:
    """On Windows, rewrite ``C:\\Users\\foo`` to ``C:/Users/foo`` so Bash
    doesn't eat the backslashes. No-op on other platforms. No-op when
    the command contains no drive-letter paths."""
    if not _IS_WINDOWS:
        return command

    def _replace(m: re.Match[str]) -> str:
        drive = m.group(1)
        rest = m.group(2).replace("\\", "/")
        return f"{drive}:/{rest}"

    return _WIN_PATH_RX.sub(_replace, command)


def _policy_for_config() -> ShellPolicy:
    """Build the always-on denylist policy from the live agent cfg.

    Reads through ``_active_cfg.active_cfg()`` so a session-scoped
    ``/allowlist add`` is immediately effective. The prior
    implementation called ``load_config()`` directly, so mid-session
    allowlist tweaks were invisible to the bash gate until the user
    restarted athena.
    """
    from ._active_cfg import active_cfg

    cfg = active_cfg()
    bash_cfg = getattr(cfg, "bash", None)
    if bash_cfg is not None:
        deny = tuple(DEFAULT_DENYLIST) + tuple(bash_cfg.extra_denylist or ())
        return ShellPolicy(allowlist=bash_cfg.allowlist, denylist=deny)
    # Defensive fallback for stub cfg objects in tests that don't carry
    # the nested BashConfig instance (SimpleNamespace fixtures).
    deny = tuple(DEFAULT_DENYLIST) + tuple(getattr(cfg, "bash_extra_denylist", ()) or ())
    return ShellPolicy(
        allowlist=getattr(cfg, "bash_allowlist", []) or [],
        denylist=deny,
    )


_IS_WINDOWS = sys.platform == "win32"

if not _IS_WINDOWS:
    import select  # POSIX-only path


def _resolve_bash_executable() -> str | None:
    """Return a path to a bash executable, or ``None`` to let ``shell=True``
    pick the platform default (cmd.exe on Windows, /bin/sh on POSIX).

    On Windows we prefer Git-for-Windows bash so commands like ``ls``,
    ``grep``, and POSIX shell quoting still work. We deliberately SKIP
    ``C:\\Windows\\System32\\bash.exe`` — that's WSL's launcher, which
    interprets paths as Linux paths and breaks ``shell=True`` invocation
    against a Windows ``cwd``. If no usable bash is found we fall back
    to cmd.exe via the default ``shell=True`` resolution.
    """
    if not _IS_WINDOWS:
        return "/bin/bash"
    # Check Git-for-Windows install locations first.
    for path in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ):
        if os.path.exists(path):
            return path
    # Then check PATH, but skip the WSL launcher under System32 /
    # WindowsApps (the App Execution Alias shim).
    for name in ("bash.exe", "bash"):
        found = shutil.which(name)
        if found and "system32" not in found.lower() and "windowsapps" not in found.lower():
            return found
    return None


_MAX_OUTPUT = 64_000

# Background process registry (id -> dict with proc, started, command, output_buf)
_BG: dict[str, dict[str, Any]] = {}
_BG_LOCK = threading.Lock()
_NEXT_BG_ID = 1


def set_max_output(n: int) -> None:
    global _MAX_OUTPUT
    _MAX_OUTPUT = n


def _truncate(out: str) -> str:
    if len(out) > _MAX_OUTPUT:
        half = _MAX_OUTPUT // 2
        return out[:half] + f"\n\n... [truncated, {len(out)} total bytes] ...\n\n" + out[-half:]
    return out


@tool(
    name="Bash",
    toolset="shell",
    aliases=["bash"],
    description=(
        "Execute a shell command and return its output. The working directory "
        "persists between commands within a turn. Output is captured "
        "(stdout+stderr merged) and truncated if very long. Default timeout "
        "120s, max 600s.\n\n"
        "PREFER FIRST-CLASS TOOLS over this one. They are faster, work the "
        "same on every OS, and don't depend on userland utilities that may "
        "not be installed (this matters on Windows where `grep`/`find`/`sed` "
        "are not native):\n"
        "  - Search file contents:    use Grep, not `grep`/`rg`\n"
        "  - Find files by name:      use Glob, not `find`/`ls`\n"
        "  - Read a file:             use Read, not `cat`/`head`/`tail`\n"
        "  - Edit a file:             use Edit, not `sed`/`awk`\n"
        "  - Write a file:            use Write, not `echo` redirects\n"
        "  - Know where you are:      use workspace_info, not `pwd`\n"
        "Use Bash for: running tests, builds, git operations, package managers, "
        "executing scripts — things first-class tools don't cover.\n\n"
        "Quote paths with spaces. Use `description` to explain non-obvious "
        "commands. Set run_in_background=true for long-running processes "
        "(servers, watchers); poll output with bash_output.\n\n"
        "WINDOWS PATHS: use forward slashes (`C:/Users/foo/bar.py`), not "
        "backslashes. Bash treats `\\` as an escape character — "
        "`python C:\\Users\\foo\\bar.py` becomes `python C:Usersfoobar.py` "
        "after Bash unwraps the escapes. (athena auto-normalizes drive-"
        "letter paths defensively, but writing them right means clearer "
        "tool calls and saved turns.)"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute via /bin/bash -c",
            },
            "description": {
                "type": "string",
                "description": "Optional 5-10 word description for the user.",
            },
            "timeout": {
                "type": "integer",
                "description": "Optional timeout in seconds (default 120, max 600).",
            },
            "run_in_background": {
                "type": "boolean",
                "description": "Run asynchronously and return a bg id.",
            },
        },
        "required": ["command"],
    },
    requires_confirmation=True,
)
def Bash(
    command: str,
    description: str = "",
    timeout: int = 120,
    run_in_background: bool = False,
) -> str:
    timeout = max(1, min(int(timeout or 120), 600))

    # Pre-normalize Windows drive paths so Bash's escape processing
    # doesn't eat the backslashes. ``python C:\Users\foo\bar.py``
    # becomes ``python C:/Users/foo/bar.py`` — accepted everywhere
    # Bash routes to on Windows (Git Bash + Python + git + MSYS tools).
    # No-op on POSIX or commands with no drive-letter paths.
    command = _normalize_windows_paths(command)

    decision = _policy_for_config().evaluate_denylist_only(command)
    if not decision.allowed:
        return f"BLOCKED by shell policy: {decision.reason}"

    if run_in_background:
        try:
            return _start_background(command)
        except SandboxUnavailableError as e:
            return f"BLOCKED by sandbox: {e}"

    console.print(f"[dim]$ {command}[/dim]")
    try:
        proc = _spawn(command)
    except SandboxUnavailableError as e:
        return f"BLOCKED by sandbox: {e}"
    if _IS_WINDOWS:
        return _stream_windows(proc, timeout)
    return _stream_posix(proc, timeout)


def _spawn(command: str, **extra_kwargs: Any) -> subprocess.Popen:
    """Construct the Popen the right way for the platform.

    POSIX: ``shell=True, executable="/bin/bash"`` works naturally.

    Windows: ``shell=True`` with a non-cmd ``executable=`` is broken — Python
    appends ``/c`` (cmd.exe's switch) and git-bash misreads it as a path.
    So we invoke bash explicitly as ``[bash_path, "-c", command]`` with
    ``shell=False``. If no bash is found, fall back to the default
    ``shell=True`` resolution (cmd.exe).

    T5-02R: when ``cfg.sandbox_enabled`` and the host can run bwrap
    (Linux + bwrap on PATH), the command is rewritten into a bwrap
    argv before Popen. Streaming + timeout above this function are
    unchanged. The shell_policy denylist still runs in the caller
    (:func:`Bash`) before this function — sandbox is
    defense-in-depth on top of the policy floor, not a replacement.
    """
    base_kwargs: dict[str, Any] = {
        "cwd": str(file_ops._WORKSPACE),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "bufsize": 0,
    }
    base_kwargs.update(extra_kwargs)
    exec_path = _resolve_bash_executable()

    # Sandbox path: only when explicitly enabled. Non-Linux + no-bwrap
    # fallback is controlled by cfg.sandbox_fallback.
    sandboxed = _maybe_sandbox(command, exec_path)
    if sandboxed is not None:
        # bwrap takes the rewritten argv with shell=False; the inner
        # argv inside the wrap is `[bash, "-c", command]` so the
        # caller's shell semantics still apply.
        return subprocess.Popen(sandboxed, shell=False, **base_kwargs)

    if _IS_WINDOWS:
        if exec_path is not None:
            return subprocess.Popen([exec_path, "-c", command], shell=False, **base_kwargs)
        # No bash available — let cmd.exe handle it.
        return subprocess.Popen(command, shell=True, **base_kwargs)
    # POSIX
    if exec_path is not None:
        return subprocess.Popen(command, shell=True, executable=exec_path, **base_kwargs)
    return subprocess.Popen(command, shell=True, **base_kwargs)


class SandboxUnavailableError(RuntimeError):
    """Raised when ``cfg.sandbox_enabled`` is True, the host can't
    sandbox, AND ``cfg.sandbox_fallback`` is ``"error"``. The caller
    (:func:`Bash`) catches this and surfaces a BLOCKED-style message
    so the agent sees a clear reason instead of an opaque Popen
    failure."""


def _maybe_sandbox(command: str, exec_path: str | None) -> list[str] | None:
    """Decide whether to rewrite ``command`` into a bwrap argv.

    Returns the rewritten argv when the sandbox kicks in, ``None``
    otherwise (caller takes the original code path). Raises
    :class:`SandboxUnavailableError` when the sandbox is required by
    config but can't run on this host.

    Lazy-imports the config + sandbox modules so this module's
    import graph stays clean for tests that don't touch shell
    execution.
    """
    import logging

    from ._active_cfg import active_cfg

    log = logging.getLogger(__name__)
    cfg = active_cfg()
    if not getattr(cfg, "sandbox_enabled", False):
        return None

    from ..sandbox.bwrap import (
        build_bwrap_command,
        explain_unavailable,
        is_bwrap_available,
    )

    if not is_bwrap_available():
        fallback = getattr(cfg, "sandbox_fallback", "warn")
        reason = explain_unavailable()
        if fallback == "error":
            raise SandboxUnavailableError(reason)
        # fallback == "warn" (also covers any unexpected value):
        # log a single line and let the un-sandboxed path run.
        log.warning("sandbox_enabled but unavailable: %s", reason)
        return None

    # Build the inner argv the same way the un-sandboxed path
    # would. We use bash explicitly so `command` is shell-string,
    # not split-by-shlex; matches the existing semantics.
    inner_exec = exec_path or "/bin/bash"
    inner = [inner_exec, "-c", command]
    return build_bwrap_command(
        inner,
        workspace=file_ops._WORKSPACE,
        allow_network=bool(getattr(cfg, "sandbox_allow_network", False)),
        writable_paths=list(getattr(cfg, "sandbox_writable_paths", []) or []),
    )


def _stream_posix(proc: subprocess.Popen, timeout: int) -> str:
    """Live-stream stdout via select() on POSIX."""
    buf: list[str] = []
    pending = b""
    # Use monotonic clock for the deadline so an NTP sync (or any
    # wall-clock adjustment) mid-command doesn't either:
    #   * fire the timeout immediately because the clock jumped
    #     forward past the deadline, killing a healthy process; or
    #   * silently extend the timeout if the clock rolled backward.
    # ``time.time()`` is wall-clock and CAN go backwards on Linux
    # (ntpdate / chronyd small adjustments are usually slewed but
    # large adjustments at boot are stepped). ``time.monotonic()``
    # guarantees forward-only motion.
    deadline = time.monotonic() + timeout
    timed_out = False
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            ready, _, _ = select.select([fd], [], [], min(remaining, 0.5))
            if ready:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break  # EOF
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    text = line.decode("utf-8", errors="replace") + "\n"
                    console.out(text, end="", highlight=False)
                    buf.append(text)
            elif proc.poll() is not None:
                break  # process exited and pipe drained
    finally:
        if timed_out and proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        rc = proc.wait()
        if pending:
            tail = pending.decode("utf-8", errors="replace")
            console.out(tail, end="", highlight=False)
            buf.append(tail)
    if timed_out:
        buf.append(f"\n[athena] command timed out after {timeout}s\n")
    out = "".join(buf)
    return f"exit={rc}\n{_truncate(out)}"


def _stream_windows(proc: subprocess.Popen, timeout: int) -> str:
    """Read stdout on a daemon thread on Windows — select() doesn't accept pipes."""
    buf: list[str] = []
    pending = b""
    lock = threading.Lock()

    def _drain() -> None:
        nonlocal pending
        assert proc.stdout is not None
        try:
            for raw_line in iter(proc.stdout.readline, b""):
                with lock:
                    text = raw_line.decode("utf-8", errors="replace")
                    console.out(text, end="", highlight=False)
                    buf.append(text)
        except Exception:
            pass

    reader = threading.Thread(target=_drain, name="athena-bash-reader", daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        timed_out = True
    # Give the reader a moment to drain final output, then move on.
    reader.join(timeout=1.0)
    rc = proc.poll()
    if timed_out:
        buf.append(f"\n[athena] command timed out after {timeout}s\n")
    out = "".join(buf)
    return f"exit={rc}\n{_truncate(out)}"


def _start_background(command: str) -> str:
    global _NEXT_BG_ID
    # stdin=DEVNULL so background children that read stdin get an
    # immediate EOF instead of competing with the parent prompt_toolkit
    # REPL for terminal ownership — without it, any child that calls
    # ``input()`` / reads ``/dev/stdin`` blocks forever holding the
    # tty, freezing the operator's keyboard. (Matches Hermes' fix #17959.)
    proc = _spawn(
        command,
        text=True,
        bufsize=1,
        errors="replace",
        stdin=subprocess.DEVNULL,
    )
    # Re-open stdout in text mode for streaming readline iteration.
    with _BG_LOCK:
        bg_id = f"bg{_NEXT_BG_ID}"
        _NEXT_BG_ID += 1
        entry: dict[str, Any] = {
            "proc": proc,
            "started": time.time(),
            "command": command,
            "buf": [],
        }
        _BG[bg_id] = entry

    # Background reader to drain stdout into the ring buffer
    def _drain() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                with _BG_LOCK:
                    entry["buf"].append(line)
                    if len(entry["buf"]) > 5000:
                        entry["buf"] = entry["buf"][-5000:]
        except Exception:
            pass

    threading.Thread(target=_drain, name=f"athena-bg-{bg_id}", daemon=True).start()
    return f"started {bg_id}: {command!r} (use bash_output {bg_id})"


@tool(
    name="bash_output",
    toolset="shell",
    description=(
        "Read pending output from a background Bash process started with "
        "run_in_background=true. Returns whatever output has accumulated since "
        "the last call, plus an exit status if the process has finished."
    ),
    parameters={
        "type": "object",
        "properties": {
            "bash_id": {"type": "string"},
        },
        "required": ["bash_id"],
    },
)
def bash_output(bash_id: str) -> str:
    with _BG_LOCK:
        entry = _BG.get(bash_id)
        if not entry:
            return f"ERROR: no background process named {bash_id!r}"
        # Drain the buffer, leave the entry so further polls work
        chunk = "".join(entry["buf"])
        entry["buf"] = []
        proc = entry["proc"]
    rc = proc.poll()
    if rc is None:
        status = f"running, started {time.time() - entry['started']:.1f}s ago"
    else:
        status = f"exit={rc}"
        # Reap the entry once the process has exited and we've drained the
        # final chunk. Prevents _BG from growing unbounded across a session.
        with _BG_LOCK:
            if bash_id in _BG and not _BG[bash_id]["buf"]:
                del _BG[bash_id]
    return f"{status}\n{_truncate(chunk)}"


@tool(
    name="kill_bash",
    toolset="shell",
    description="Kill a background Bash process by id. Returns its exit code.",
    parameters={
        "type": "object",
        "properties": {
            "bash_id": {"type": "string"},
        },
        "required": ["bash_id"],
    },
    requires_confirmation=False,
)
def kill_bash(bash_id: str) -> str:
    with _BG_LOCK:
        entry = _BG.get(bash_id)
    if not entry:
        return f"ERROR: no background process named {bash_id!r}"
    proc = entry["proc"]
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    rc = proc.poll()
    with _BG_LOCK:
        _BG.pop(bash_id, None)
    return f"{bash_id}: exit={rc}"
