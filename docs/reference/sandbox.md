# Sandbox

Optional OS-level isolation for the Bash tool. When
`sandbox_enabled = true`, every shell command athena runs is
wrapped in a [bubblewrap](https://github.com/containers/bubblewrap)
jail: read-only system, writable workspace only, no network by
default. Linux-only.

The sandbox is **defense-in-depth on top of the shell_policy
denylist**, not a replacement. The denylist always runs first as
the security floor — a denylisted command (`rm -rf /`, etc.) is
blocked before the sandbox decision ever fires.

## What gets sandboxed

Every command that goes through `athena/tools/shell.py:_spawn`:

- the `Bash` tool foreground path
- the `Bash` tool with `run_in_background=true`
- subsequent reads via `bash_output` (already operating on the
  sandboxed `Popen` handle)

In other words: every command the agent runs.

## Defaults

| Field | Default | Notes |
|-------|---------|-------|
| `sandbox_enabled` | `false` | Opt-in. Off → byte-identical to today |
| `sandbox_backend` | `"bwrap"` | Only backend today |
| `sandbox_allow_network` | `false` | `--unshare-net` blocks all outbound traffic |
| `sandbox_writable_paths` | `[]` | Workspace alone is bound writable |
| `sandbox_fallback` | `"warn"` | `"warn"` runs unsandboxed + logs; `"error"` refuses |

## What the bwrap argv looks like

For `Bash(command="echo hi")` with a workspace at `/tmp/proj`:

```
bwrap
  --die-with-parent
  --new-session
  --unshare-pid --unshare-ipc --unshare-uts --unshare-cgroup
  --unshare-net                       # default: no network
  --cap-drop ALL
  --ro-bind / /
  --proc /proc
  --dev /dev
  --tmpfs /tmp
  --bind /tmp/proj /tmp/proj          # writable workspace
  --setenv HOME /tmp/proj
  --chdir /tmp/proj
  --
  /bin/bash -c "echo hi"
```

Read-only root + writable workspace is the safe default. Setting
`HOME` to the workspace stops tools that touch `~/.cache`,
`~/.config`, or `~/.ssh` from escaping the bind set.

## Adding writable paths

For workflows that need an out-of-tree cache or build dir:

```toml
sandbox_writable_paths = ["~/.cache/pip", "/tmp/build-out"]
```

Each entry becomes an additional `--bind <p> <p>` in the argv.
The workspace is always writable; the list extends, doesn't
replace.

## Enabling network

```toml
sandbox_allow_network = true
```

Drops `--unshare-net`. The command inherits the host network
namespace and can reach the internet. The shell_policy denylist
still runs first; denylisted exfil patterns (e.g.
`curl -d @secrets.txt`) stay blocked.

## Fallback when bwrap isn't available

The sandbox is Linux-only and requires `bwrap` on PATH. When
either check fails:

- `sandbox_fallback = "warn"` (default) — log a one-line
  warning and run unsandboxed. Headless installs without bwrap
  keep working with just the denylist.
- `sandbox_fallback = "error"` — refuse every Bash invocation
  with `"BLOCKED by sandbox: <reason>"`. Use this when the
  sandbox is a hard requirement.

On Windows and macOS the sandbox can't run; `"warn"` falls
through cleanly. Install bwrap:

| Distro | Command |
|--------|---------|
| Debian/Ubuntu | `apt install bubblewrap` |
| Fedora | `dnf install bubblewrap` |
| Arch | `pacman -S bubblewrap` |
| Alpine | `apk add bubblewrap` |

## The denylist floor

`athena/safety/shell_policy.py:DEFAULT_DENYLIST` enforces a hard
floor of blocked patterns (destructive `rm`, sudo, system service
control, etc.) regardless of sandbox state. Configurable
extension via `cfg.bash_extra_denylist`. This runs in `Bash()`
BEFORE `_spawn` ever sees the command — denylisted input never
reaches the sandbox decision path.

## Streaming, timeout, kill

Unchanged. The Popen the sandbox produces is still a normal
`subprocess.Popen` that `_stream_posix` and `_stream_windows`
drive. `--die-with-parent` ensures the sandboxed child dies if
athena exits or `proc.kill()` fires.

## What this is not

- **Not a container.** No image, no rootfs, no resource limits.
  Filesystem isolation + namespace isolation + cap drop — enough
  to keep an errant `rm -rf` from wandering out of the workspace,
  not enough to safely run untrusted code from the internet.
- **Not a privilege boundary.** bwrap inherits athena's uid; the
  jail isolates *what athena can touch*, not "what an attacker
  who got code execution can do."
- **Not platform-portable.** Linux-only by design. The macOS /
  Windows equivalents (Mac sandbox-exec, Windows containers) are
  out of scope.

## Testing

35 unit tests in `tests/sandbox/`:

- `test_bwrap.py` (21) — argv build shape, network toggle, bind
  set, namespace flags, availability detection, error explainer.
- `test_shell_integration.py` (12) — `_spawn` rewrites under
  the right conditions, fallback semantics, denylist precedence,
  timeout preservation.

Everything is hermetic via Popen stubs; no real subprocess
fires.
