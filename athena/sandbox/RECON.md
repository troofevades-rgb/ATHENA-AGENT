# T5-02R recon — sandbox seam over athena's existing Bash spawn

## (a) `_spawn` is the single wrap point

`athena/tools/shell.py` is a flat module with three entry points
that all funnel into `_spawn(command, **extra_kwargs)`:

| Caller | Line | Path |
|--------|------|------|
| `Bash()` (foreground) | 144 | `proc = _spawn(command)` → `_stream_{posix,windows}` |
| `Bash()` (background) | 141 | `_start_background(command)` → `_spawn(command, text=True, ...)` |
| `bash_output` / `kill_bash` | n/a | operate on the live `proc` handle |

Everything else (timeout enforcement, streaming, ring-buffered
output, foreground/background distinction) sits above `_spawn`.
Rewriting the command inside `_spawn` is the natural sandbox seam:
one change, every shell invocation goes through it.

`_spawn` signature today:

```python
def _spawn(command: str, **extra_kwargs: Any) -> subprocess.Popen:
    base_kwargs = {
        "cwd": str(file_ops._WORKSPACE),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "bufsize": 0,
    }
    base_kwargs.update(extra_kwargs)
    exec_path = _resolve_bash_executable()
    if _IS_WINDOWS:
        if exec_path:
            return subprocess.Popen([exec_path, "-c", command], shell=False, **base_kwargs)
        return subprocess.Popen(command, shell=True, **base_kwargs)
    if exec_path:
        return subprocess.Popen(command, shell=True, executable=exec_path, **base_kwargs)
    return subprocess.Popen(command, shell=True, **base_kwargs)
```

The sandbox wraps `command` into a `bwrap`-prefixed argv only
when conditions permit; the existing Popen invocation is
otherwise byte-identical.

## (b) The denylist runs BEFORE spawn — must stay first

`athena/tools/shell.py:136`:

```python
decision = _policy_for_config().evaluate_denylist_only(command)
if not decision.allowed:
    return f"BLOCKED by shell policy: {decision.reason}"
```

`_policy_for_config()` returns a `ShellPolicy` initialised with
`DEFAULT_DENYLIST` from `athena/safety/shell_policy.py` plus
`cfg.bash_extra_denylist`. The check fires for every Bash call
before `_spawn` runs.

**Invariant:** the sandbox does not move, rewrite, or replace this
check. The denylist is the security floor; the sandbox is
defense-in-depth on top. A denylist hit short-circuits — the
sandbox path never runs.

## (c) Timeout + streaming are above `_spawn`

`_spawn` only constructs the `Popen`. Timeout enforcement and
output streaming live in:

- `_stream_posix(proc, timeout)` — `select()` loop with a
  `deadline` timer (line 180+). Kills the proc on overrun and
  appends `[athena] command timed out after Ns`.
- `_stream_windows(proc, timeout)` — thread + queue with the
  same overrun semantics (line 225+).
- `_start_background(command)` — spawns then registers in a
  module-level `_BG` dict; `bash_output` polls.

Because the sandbox only rewrites `command` inside `_spawn`, the
`Popen` it returns still drives the same streaming + timeout
code path. `proc.kill()` reaches the bwrap parent; bwrap's
`--die-with-parent` ensures the child process group dies with it.
No streaming code changes needed.

## (d) Platform branch — Linux-only, configurable fallback

`bwrap` (bubblewrap) is Linux-only. On Windows / macOS / Linux
without bwrap installed, the sandbox falls back per
`cfg.sandbox_fallback`:

- `"warn"` — log a one-line warning and run unsandboxed.
- `"error"` — refuse the command with a clear message ("Sandbox
  required by config but bubblewrap unavailable; install bwrap
  or set sandbox_enabled=false").

`is_bwrap_available()` checks `shutil.which("bwrap")` and
`sys.platform == "linux"`. Both must be true.

Cross-platform parity isn't a goal: the sandbox is a Linux-only
opt-in. Windows / macOS users get the same behaviour they have
today (denylist only).

## Plan

1. `athena/sandbox/__init__.py` + `bwrap.py` — pure functions,
   no I/O at module load. `build_bwrap_command(inner_cmd, *,
   cfg, workspace) → list[str]`, `is_bwrap_available()` →
   `bool`.
2. Config — `sandbox_enabled` (False), `sandbox_backend`
   ("bwrap"), `sandbox_allow_network` (False),
   `sandbox_writable_paths` ([] — the workspace is implicit),
   `sandbox_fallback` ("warn").
3. `tools/shell.py:_spawn` checks `cfg.sandbox_enabled` and
   wraps the command into the bwrap argv before constructing the
   `Popen`. Otherwise calls today's `Popen` unchanged.
4. Tests: pure-function tests for the argv build; integration
   tests with a stubbed `Popen` to confirm the wrap kicks in
   under the right conditions and doesn't kick in otherwise.

## Cross-phase note

T5-02R doesn't touch `ShellPolicy` / `DEFAULT_DENYLIST` /
`bash_extra_denylist` / `bash_allowlist`. The denylist is the
security floor; the sandbox layers OS-level isolation on top.
This means: even if the sandbox config disables network, a
denylisted `curl -d @secrets.json` is still blocked at the
policy level before bwrap ever runs.
