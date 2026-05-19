# Safety reference

Athena treats every agent-driven mutation as a forensic event:
something to be snapshotted before, audited after, and rolled back
on demand. This document is the operator-facing reference for the
Phase 17 safety subsystem.

## At a glance

| Concern | Mechanism | Storage |
|---|---|---|
| Pre-state recoverability | Content-addressed tarball snapshots | `~/.athena/snapshots/YYYY/MM/DD/<id>.tar.gz` |
| Mutation provenance | Append-only JSONL audit log | `~/.athena/audit/mutations-YYYY-MM.jsonl` |
| Approval scoping | ContextVar grant cache, denied in background | in-process only |
| Shell safety | Word-boundary allowlist + always-on denylist | `[shell]` config |
| CI regression guard | Frozen raw-write allowlist | `tests/safety/test_no_raw_writes.py` |

## Write origins

Every tool call runs under exactly one `write_origin` value
(implemented as a `ContextVar` in `athena.provenance`):

- `foreground` — the user asked for it directly. Approvals prompt;
  default snapshotting is off (configurable via
  `[safety] snapshot_foreground`).
- `background_review` — per-turn review fork (Phase 4). Mutations
  must be explicitly allowed via `auto_approve_in_background=True`
  on the resource, otherwise approval calls raise
  `ApprovalDeniedInBackground`.
- `curator` — skill-curator fork (Phase 4). Same denial rules as
  `background_review`.
- `migration` — one-shot Hermes → Athena import. Recorded with
  `write_origin=migration` for audit but not subject to runtime
  approval gating.
- `system` — internal lifecycle (loader cache invalidation,
  metadata bookkeeping). Not counted toward user-facing audit.

The origin is the *single* attribute that determines approval
behaviour. Read it from anywhere via
`athena.provenance.get_current_write_origin()`.

## Snapshots

Every agent-driven mutation routes through
`athena.safety.mutation.snapshot_and_record(paths, tool_name=...)`,
which:

1. Hashes the listed paths to derive a content address.
2. Builds a gzipped tar of the pre-state.
3. Writes the tar + a sidecar JSON under
   `~/.athena/snapshots/YYYY/MM/DD/<unix_ts>-<sha[:12]>-<origin>.tar.gz`.
4. Yields a `MutationContext` to the caller's mutation block.
5. After mutation, the caller calls `ctx.record(path)` to emit a
   `MutationRecord` (see "Audit log" below).

Identical pre-state under the same write origin at the same
unix-second collapses to one tarball on disk — re-running a curator
that ultimately touches nothing doesn't burn 10× the bytes.

### Inspect

```sh
athena snapshot list                            # newest first
athena snapshot list --write-origin curator
athena snapshot list --path ~/.athena/skills/demo
athena snapshot show <snapshot_id>              # sidecar + tar listing
```

### Pin

Pinned snapshots survive every prune pass. Pin a snapshot you want
to keep regardless of retention policy:

```sh
athena snapshot pin <snapshot_id>
athena snapshot unpin <snapshot_id>
```

### Prune

Retention is governed by three independent rules; whichever fires
first wins, and pinned snapshots bypass all of them:

| Rule | Default | Config key |
|---|---|---|
| Age | 90 days | `[safety] retention_days` |
| Count | 5 000 snapshots | `[safety] retention_count` |
| Total size | 5 GB | `[safety] retention_bytes` |

```sh
athena snapshot prune --dry-run                 # show what would go
athena snapshot prune                           # apply
```

## Rollback

Two convenience entrypoints sit on top of the snapshot store:

```sh
athena skill diff <name>                        # diff vs. most recent snapshot
athena skill diff <name> --to <snapshot_id>
athena skill rollback <name> [-y]               # interactive y/N

athena memory diff <name>
athena memory rollback <name> [-y]
```

Rollbacks are themselves audited — the post-restore record carries
`tool_name="skill_rollback"` (or `memory_rollback`) with
`sha_before`/`sha_after` inverting the original mutation. A
hostile rollback is therefore as visible in the audit log as the
mutation it reverses.

## Audit log

One compact JSON line per mutation:

```json
{"timestamp":"2026-05-17T12:34:56+00:00","write_origin":"curator",
 "session_id":"s-abc","parent_session_id":"s-parent",
 "tool_name":"skill_patch","tool_call_id":"call-7",
 "path":"/.../SKILL.md","snapshot_id":"...",
 "sha_before":"...","sha_after":"...","byte_delta":42}
```

- Files rotate monthly: `mutations-2026-05.jsonl`, `mutations-2026-06.jsonl`, …
- `threading.Lock` serialises appends; the file is opened in `"a"`
  mode so existing content always survives.
- `wc -l mutations-*.jsonl` counts mutations; `jq` is the
  recommended pipeline.

## Approval guard

`athena.safety.approval_guard.request_approval` is the single
funnel for any tool action that should prompt in foreground but be
denied in background:

```python
ok = await request_approval(
    f"skill:{name}", prompt_callback,
    auto_approve_in_background=False,
)
```

Behaviour by origin:

- **foreground** — prompt is called; result cached for the lifetime
  of the current ContextVar scope. A second call with the same
  resource id returns the cached value.
- **background_review / curator / migration / system** — raises
  `ApprovalDeniedInBackground` unless
  `auto_approve_in_background=True`. The prompt callback is never
  invoked from background, even if the same resource has a cached
  foreground grant. `Agent.fork()` calls `scope_fresh_approvals()`
  at thread entry so background forks start with an empty cache by
  construction.

## Shell policy

The Bash tool's denylist is always on; the allowlist is
opt-in (drives approval-bypass, not absolute denial). Allowlist
entries compile to `^<escaped-entry>\b` so:

- `git` allows `git status`, `git push --force`, `FOO=bar git ...`
- `git` does **not** allow `gitlab-cli`, `gitleaks`, `.git/hooks/...`
- `ls` does **not** allow `lsof`

Default denylist (verbatim regex strings):

```
\brm\s+-rf\s+/(?!home/|tmp/|var/tmp/)
\bdd\s+.*\bof=/dev/(sd|nvme|hd)
\bmkfs\.
:\(\)\s*\{\s*:\|:&\s*\}\s*;:
>\s*/dev/(sda|nvme|hda)
\bchmod\s+.*\b777\b\s+/
\bsudo\s+rm\s+-rf
\bcurl\b.*\|\s*(sudo\s+)?(sh|bash|zsh)
\bwget\b.*\|\s*(sudo\s+)?(sh|bash|zsh)
```

Extend via config:

```toml
bash_allowlist = ["git", "ls", "cat", "python"]
bash_extra_denylist = [
    "\\bgcloud\\s+iam\\s+roles\\s+delete",  # custom paranoia
]
```

A denied command returns `"BLOCKED by shell policy: <reason>"` as
the tool result — the agent sees the rejection and can react.

## CI regression guard

`tests/safety/test_no_raw_writes.py` walks `athena/` and flags any
module that:

- isn't on the frozen allowlist, AND
- calls `.write_text(`, `.write_bytes(`, `open(..., "w")`,
  `shutil.copy*`, or `shutil.rmtree`.

When a new mutation path lands:

1. Prefer routing through
   `athena.safety.mutation.snapshot_and_record`.
2. Only add to the allowlist when the write is genuinely outside
   the snapshot-and-audit scope (cache files, append-only audit
   substrates, transactional config writes with their own atomic
   rename).

The allowlist isn't there to be loose — every entry is a
justification entered with the eyes-open knowledge that *the
operator can't roll this path back*.

## Config block

```toml
[safety]
snapshot_foreground = false          # default: skip snapshotting foreground writes
retention_days = 90
retention_count = 5000
retention_bytes = 5368709120          # 5 GB

# Shell policy lives in the top-level config:
bash_allowlist = ["git", "ls", "cat"]
bash_extra_denylist = []
```

## Secure file writes (T1-06)

Files holding secret material — provider credentials, OAuth tokens,
imported API keys — go through `athena.safety.secure_files`. The
contract closes the TOCTOU window where a credential file briefly
exists at the system default umask (often `0o644`) before being
`chmod`-ed to `0o600`.

| Operation | Function | Mode |
|---|---|---|
| Write text | `secure_write_text(path, text)` | `0o600` |
| Write JSON | `secure_write_json(path, obj)` | `0o600` |
| Read text | `secure_read_text(path)` | warns on `> 0o600` |
| Read JSON | `secure_read_json(path)` | warns on `> 0o600` |
| Create dir | `ensure_secure_dir(path)` | `0o700` |

Under the hood the write path is:

1. `os.open(<tmp>, O_CREAT|O_WRONLY|O_EXCL, 0o600)` — no window at
   wider mode, no symlink-clobber race.
2. `os.fdopen` → write → `flush` → `fsync`.
3. `fsync` the parent directory (POSIX only — Windows has no
   `O_DIRECTORY`).
4. `os.replace(<tmp>, <dest>)` — atomic on POSIX and Windows 10+.
   On Windows transient `PermissionError` from concurrent peers is
   retried with backoff.
5. `fsync` the parent directory again.

The 50-thread regression test in `tests/safety/test_secure_files.py`
exercises the concurrent-fork path: 50 threads writing the same
destination must converge to one consistent file at `0o600`.

`ensure_secure_dir` deliberately does not re-`chmod` existing
directories at wider modes. A `WARNING` is logged so the operator
can audit and `chmod` themselves rather than the agent silently
mutating filesystem state.

Surfaces migrated to `secure_files`:

- `athena/providers/credential_pool.py` — `credentials.json`
- `athena/mcp/oauth.py` — `~/.athena/mcp_tokens/<server>.json`
- `athena/migration/config_translator.py` — Hermes-import credential
  carry-over

## Path security (T1-07)

`athena/tools/file_ops.py` is sandboxed to the workspace via
`athena.safety.path_security.validate_path`. Every `Read`, `Write`,
`Edit`, and `list_dir` call resolves the input path and passes it
through the validator before opening any file.

Resolution order:

1. Resolve the path (follows symlinks).
2. If the resolved path matches an **absolute-deny** pattern, refuse.
   Approval cannot override.
3. If the resolved path is **inside the workspace**, allow.
4. If the resolved path matches an **always-allowed prefix**, allow.
5. If `allow_external()` is active on this context, allow.
6. Otherwise, prompt the active approval callback. `"allow"` returns
   the path; anything else raises `PathSecurityDenied`.

**Always-allowed prefixes** (no prompt, even outside the workspace):

- `~/.athena/**` — athena's own state directory
- `~/.config/athena/**`
- `/tmp/athena-**` — scratch dirs the agent itself created
- `/var/folders/*/*/T/athena-**` — macOS TMPDIR shape

**Absolute-deny patterns** (refuse regardless of approval):

- `/proc/<pid>/mem`, `/proc/kcore`
- `/dev/mem`, `/dev/kmem`, `/dev/port`
- `/dev/sd[a-z]<n>`, `/dev/nvme<n>n<m>` raw block devices
- `/sys/firmware/efi/efivars/*` — corrupting these can brick a host
- Windows raw-device paths: `\\.\PHYSICALDRIVE<n>`, `\\.\Volume{...}`

**Workspace is a `ContextVar`.** `Agent.__init__` sets it via
`file_ops.set_workspace` (which delegates to `path_security.set_workspace`).
Forks run in daemon threads and do **not** inherit `ContextVar` values
across thread boundaries, so the fork runner re-pins the workspace
explicitly before installing `AUTO_DENY`. Net effect: forks cannot
escape the parent's workspace under any circumstances.

**Test isolation.** `tests/conftest.py` installs an autouse
`_path_security_workspace` fixture that points the workspace at
`tmp_path` for every test. Tests that legitimately need to operate
outside `tmp_path` wrap their call in
`with athena.safety.path_security.allow_external():`.

**Approval callback contract.** The project's approval callback is
`(tool_name: str, args: dict) -> "allow"|"deny"`. `validate_path`
calls `callback("path_security", {intent, path, workspace})`. Forks
have `AUTO_DENY` installed, so any outside-workspace operation from
a fork raises `PathSecurityDenied` without prompting.

**Audit logging.** Approved outside-workspace operations fire
`audit_append(kind="path_security_approval", payload={intent, path,
workspace})`. The default implementation is a `logger.warning` with
a grep-able structured prefix; tests monkeypatch the symbol to
capture calls.

## URL safety (T1-08)

`athena/tools/web.py` is sandboxed via
`athena.safety.url_safety.validate_url`. `WebFetch` validates the
user-supplied URL before the httpx fetch, and an httpx event hook
re-validates every redirect target so a 30x `Location:` header
pointing at a blocked IP is refused just like a direct fetch.

**Block list (IPv4):** `0.0.0.0/8`, `10.0.0.0/8`, `100.64.0.0/10`
(carrier-grade NAT — AWS metadata fallback), `127.0.0.0/8`,
`169.254.0.0/16` (link-local AND `169.254.169.254` cloud metadata),
`172.16.0.0/12`, `192.0.0.0/24`, `192.0.2.0/24`, `192.168.0.0/16`,
`198.18.0.0/15`, `198.51.100.0/24`, `203.0.113.0/24`, `224.0.0.0/4`
(multicast), `240.0.0.0/4`, `255.255.255.255/32`.

**Block list (IPv6):** `::/128`, `::1/128`, `64:ff9b::/96`,
`100::/64`, `fc00::/7` (ULA), `fe80::/10` (link-local),
`fd00:ec2::254/128` (AWS IMDSv2 v6), `ff00::/8` (multicast).
IPv4-mapped IPv6 addresses (`::ffff:0:0/96`) re-check against the
IPv4 list, so `::ffff:127.0.0.1` is blocked.

**Schemes:** only `http` and `https` allowed. `file:`, `ftp:`,
`gopher:`, `jar:`, `dict:`, `data:` with binary, etc. all refused.

**Approval contract.** Same shape as path security:
`(tool_name, args) -> "allow"|"deny"`. `validate_url` invokes
`callback("url_safety", {url, resolved_ips, blocked_ips})`. Forks
have `AUTO_DENY` installed, so any blocked URL from a fork raises
`URLSecurityDenied` without prompting.

**Escape hatch.** Tests fetching from localhost test servers, or a
foreground tool reaching a user-configured private SearxNG, wrap
the call in `with athena.safety.allow_external_urls():`. Bypass
events fire `audit_append(kind="url_security_allow_external_bypass")`
so even allowed bypasses are recorded.

**Fail-closed on DNS failure.** `socket.getaddrinfo` errors raise
`URLSecurityDenied` rather than allow the fetch through. An attacker
cannot bypass validation by giving us a host that fails DNS in a way
that crashes the validator.

**Hardcoded URLs are not validated.** `_search_duckduckgo` and
`_search_brave` hit public search endpoints under our control; they
skip `validate_url` with an inline justification comment.

## Operational playbook

**An agent edit broke a skill.**

1. `athena skill diff <name>` to see what changed.
2. `athena skill rollback <name>` (review the diff, confirm y).
3. Audit log records the rollback; pin the snapshot if the
   compromised state is forensically interesting:
   `athena snapshot pin <snapshot_id>`.

**An autonomous fork is doing something it shouldn't.**

1. `athena snapshot list --write-origin background_review` to see
   recent background activity.
2. Optionally `athena snapshot show <id>` to inspect any one event.
3. Mark the affected skill/memory as foreground-authored or pinned
   (Phase 4 curator policy) so it becomes inviolate.

**Audit log is getting large.**

Monthly files roll over automatically; archive them somewhere else
or just leave them. They append at sub-microsecond cost; size is
the only concern, never write throughput.
