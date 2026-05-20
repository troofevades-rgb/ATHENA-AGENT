# athena audit — time-bounded diffs over the audit log

Two read-only CLI subcommands replay athena's existing
`MutationAuditLog` between any two timestamps and produce a precise
record of what changed:

```bash
athena audit skill <since> <until> [--json] [--actor ACTOR]
athena audit memory <since> <until> [--json] [--actor ACTOR]
```

Note the parent: it's `athena audit`, not `athena skill diff`.
`athena skill diff <name>` already exists in the codebase as a
per-skill snapshot diff (single named skill vs. its most recent
SnapshotStore tarball). T3-04 is time-bounded over the audit log
— same word "diff", different semantics — so it lives under a new
parent. The MCP tool `athena_audit_query` parallels this.

## Quick start

```bash
athena audit skill 24h now                  # last 24 hours, skill mutations
athena audit memory 1w now --json | jq      # last week, memory, JSON
athena audit skill boot now                 # since this session started
athena audit memory last-checkpoint now     # since the most-recent checkpoint
athena audit skill 2026-05-15T00:00:00Z now --actor curator
```

## Timestamp forms

| Form | Example | Meaning |
|------|---------|---------|
| ISO 8601 | `2026-05-20T12:00:00Z`, `2026-05-20` | Absolute UTC |
| Relative | `30s`, `5m`, `2h`, `3d`, `1w` | Ago-from-now |
| Special | `now` | Current UTC |
| Special | `boot`, `session-start` | First message of active session JSONL |
| Special | `last-checkpoint` | Most-recent T3-03 checkpoint's `created_at` |

`<since>` must be strictly earlier than `<until>`.

## Output (default — human-readable)

```
Skill changes between 2026-05-15T00:00:00Z and 2026-05-20T18:23:57Z:

+ Created: alpha
     at 2026-05-15T10:00:00Z by foreground (tool: skill_create)
     sha: ∅           -> abc123       (+42 bytes)
     snapshot: snap-1
     diff: [content not in audit log — recover from snapshot]

~ Modified: api-client-generator
     at 2026-05-16T11:45:01Z by curator (tool: skill_patch)
     sha: 8f3d2c       -> 9e2b41       (+127 bytes)
     ...

Rollback / checkpoint events in this window (some changes above may have been reverted):
    2026-05-18T14:30:00Z  rollback  Rolled back to checkpoint 'before-refactor' (id=cp-...)

Summary: 1 added, 1 modified, 0 removed over 5 days, 18 hours
```

## Output (`--json`)

```json
{
  "since": "2026-05-15T00:00:00Z",
  "until": "2026-05-20T18:23:57Z",
  "events": [
    {
      "timestamp": "2026-05-15T10:00:00Z",
      "tool_name": "skill_create",
      "skill_name": "alpha",
      "write_origin": "foreground",
      "sha_before": null,
      "sha_after": "abc123",
      "byte_delta": 42,
      "path": "/.../.athena/skills/alpha/skill.md",
      "snapshot_id": "snap-1"
    }
  ],
  "rollbacks": [
    {
      "timestamp": "2026-05-18T14:30:00Z",
      "event_type": "rollback",
      "summary": "Rolled back to checkpoint 'before-refactor' (id=cp-...)",
      "data": {"rolled_back_to": "cp-...", "pre_rollback_checkpoint": "cp-..."}
    }
  ],
  "summary": {"added": 1, "modified": 0, "removed": 0}
}
```

Pipe into `jq`, save to a file, or feed into any tooling that
expects a stable JSON shape.

## What gets classified as what

`tool_name` from `MutationAuditLog` decides the bucket:

| tool_name | Skill / Memory | Category |
|-----------|----------------|----------|
| `skill_create` | skill | added |
| `skill_patch` | skill | modified |
| `skill_write_file` | skill | modified |
| `skill_rollback` | skill | modified |
| `skill_delete` | skill | removed |
| `memory_write` (sha_before null) | memory | added |
| `memory_write` (sha_before set) | memory | modified |
| `memory_delete` | memory | removed |

Mutations with any other `tool_name` are ignored (file_ops.Write
to arbitrary paths, patch_apply, etc.).

## Content diff

`MutationAuditLog` stores SHA digests + byte deltas, **not** full
file content. The diff prints `sha_before -> sha_after (+N bytes)`
and notes `[content not in audit log — recover from snapshot]`.
Full text diff is reserved for a follow-up that extracts the
snapshot tarball on demand.

This is by design: the audit log itself isn't an integrity-or-
nothing surface — it's a forensic record of *what changed*. The
content lives in the `SnapshotStore` tarball that
`snapshot_and_record` always creates alongside the audit entry.

## Cross-reference with rollback events

If a T3-03 rollback (or auto-checkpoint) falls in the window,
the diff surfaces it after the skill/memory events with a note
that *some shown changes may have been reverted*. Pass
`--no-rollback-markers` to suppress this section.

## Filtering

- `--actor <write_origin>` — only events where `write_origin` is
  one of `foreground`, `curator`, `background_review`,
  `migration`, `system`.
- `--profile <name>` — target a non-active profile.

Filtering by skill name or memory topic is a future enhancement
(deliberate scope cut from the original spec).

## Limitations

- Hash-only diff (see "Content diff" above).
- Audit log scanning is linear; with very large logs (>100 MB)
  consider an external index. Audit-log rotation by month
  (`mutations-YYYY-MM.jsonl`) keeps single-file size bounded in
  practice.
- The MCP `athena_audit_query` tool (T3-02) queries the same
  data with a slightly different interface (no time-window diff;
  just record list). Both surfaces share the underlying JSONL
  files.
