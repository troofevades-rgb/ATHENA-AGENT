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
