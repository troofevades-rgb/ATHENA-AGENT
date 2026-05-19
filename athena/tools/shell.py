"""Bash execution tool. Subject to the agent's confirmation gate
(unless the command matches the bash_allowlist or auto_approve_tools is set).
"""

from __future__ import annotations

import os
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


def _policy_for_config() -> ShellPolicy:
    """Build the always-on denylist policy from current config.

    Imported lazily so the config singleton is read fresh on each
    call — useful in tests that rebuild Config between cases.
    """
    from ..config import load_config

    cfg = load_config()
    deny = tuple(DEFAULT_DENYLIST) + tuple(getattr(cfg, "bash_extra_denylist", ()))
    return ShellPolicy(allowlist=cfg.bash_allowlist, denylist=deny)


_IS_WINDOWS = sys.platform == "win32"

if not _IS_WINDOWS:
    import select  # type: ignore  # POSIX-only path


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
        "Executes a given bash command and returns its output. The working "
        "directory persists between commands within a turn. Output is captured "
        "(stdout+stderr merged) and truncated if very long. Default timeout "
        "120s, max 600s.\n\n"
        "Avoid `cat`/`head`/`tail`/`sed`/`awk`/`echo`; prefer the Read/Edit/"
        "Write tools instead. Quote paths with spaces. Use `description` to "
        "explain non-obvious commands. Set run_in_background=true for long-"
        "running processes (servers, watchers); poll output with bash_output."
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

    decision = _policy_for_config().evaluate_denylist_only(command)
    if not decision.allowed:
        return f"BLOCKED by shell policy: {decision.reason}"

    if run_in_background:
        return _start_background(command)

    console.print(f"[dim]$ {command}[/dim]")
    proc = _spawn(command)
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
    """
    base_kwargs: dict[str, Any] = {
        "cwd": str(file_ops._WORKSPACE),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "bufsize": 0,
    }
    base_kwargs.update(extra_kwargs)
    exec_path = _resolve_bash_executable()
    if _IS_WINDOWS:
        if exec_path is not None:
            return subprocess.Popen([exec_path, "-c", command], shell=False, **base_kwargs)
        # No bash available — let cmd.exe handle it.
        return subprocess.Popen(command, shell=True, **base_kwargs)
    # POSIX
    if exec_path is not None:
        return subprocess.Popen(command, shell=True, executable=exec_path, **base_kwargs)
    return subprocess.Popen(command, shell=True, **base_kwargs)


def _stream_posix(proc: subprocess.Popen, timeout: int) -> str:
    """Live-stream stdout via select() on POSIX."""
    buf: list[str] = []
    pending = b""
    deadline = time.time() + timeout
    timed_out = False
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    try:
        while True:
            remaining = deadline - time.time()
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
