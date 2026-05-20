# Conversation-level checkpoints and rollback

`/checkpoint` and `/rollback-to` save a named restore point and
revert the conversation, file state, skill registry, and memory
store to it. Hermes-class agents treat conversations as monotonic;
athena lets you abort cleanly when a long exploratory chain
turns out to be wrong, without losing the dead-end work for audit.

## Quick start

In an interactive session:

```
> /checkpoint before-refactor
✓ checkpoint created: cp-abc123 (label='before-refactor')

> [chat where the agent edits a bunch of files]

> /rollback-to before-refactor
✓ rolled back to 'before-refactor' (cp-abc123). pre-rollback state captured for undo.
```

Non-interactive:

```bash
athena checkpoint --label "before-refactor"
athena checkpoint list
athena checkpoint rollback "before-refactor"
athena checkpoint purge     # drop auto-created pre-rollback entries
```

`athena checkpoint` defaults to the most recently-modified session
under the active profile; pass `--session <id>` to target a
specific one.

## What gets captured

A checkpoint records four things:

1. **Session message offset** — the line count of the session
   JSONL at checkpoint time. Rollback truncates the log back to
   this number of messages.
2. **File snapshot id** — a content-addressed tarball of any
   files modified between the previous checkpoint and this one
   (tracked automatically when the agent uses the `Write`, `Edit`,
   or `patch_apply` tools).
3. **Skill state token** — a manifest hash plus saved content of
   every `*.md` under the user-level and workspace skill search
   paths. Restore re-writes any file whose current content
   differs.
4. **Memory state token** — same shape for `<profile>/memory/*.md`.

Storage cost per checkpoint is typically under 100 KB. File
snapshots are content-addressed so unchanged files don't re-store;
skill/memory snapshot blobs are SHA-keyed so identical content
across checkpoints shares a single copy on disk.

## What rollback does

In order:

1. **Auto pre-rollback checkpoint** — captures the current state
   first as `pre-rollback-of-<id>`, so the rollback itself is
   undoable. Any externally-modified files that would otherwise
   be silently overwritten are preserved here.
2. **Truncate the session log** to the captured offset.
3. **Restore files** from the captured file snapshot
   (`SnapshotStore.restore`).
4. **Restore skills** — any skill file whose hash differs from the
   captured copy is overwritten.
5. **Restore memory** — same for memory entries.
6. **Append a synthetic system marker** to the now-truncated log:
   `[Session rolled back to checkpoint 'label' (id=...) at
   <ts>. The intervening turns and any file/skill/memory
   mutations have been reverted.]`
7. **Audit log** — emits `event_type=checkpoint` and
   `event_type=rollback` entries to
   `<checkpoint_dir>/audit.jsonl`.

After the on-disk truncation, the slash command reloads
`agent.messages` from the shortened log so the next provider call
sees the rolled-back state.

## Undoing a rollback

Every rollback auto-creates a `pre-rollback-of-<id>` checkpoint
covering the current state. To undo:

```
> /checkpoints
  cp-aaa  2026-05-20T...  before-refactor
  cp-bbb  2026-05-20T...  pre-rollback-of-cp-aaa  (Auto-created ...)

> /rollback-to pre-rollback-of-cp-aaa
✓ rolled back to 'pre-rollback-of-cp-aaa' (cp-bbb).
```

When you no longer need them:

```
> /checkpoints purge
✓ purged 3 pre-rollback checkpoint(s)
```

`purge` only removes `pre-rollback-*` entries — user-labeled
checkpoints stay.

## In-flight protection

Calling rollback while a tool call is mid-flight raises
`InFlightToolCallError`. The slash command surfaces this as
*"Cannot rollback while a tool call is in flight. Cancel the
current turn first."* The Agent sets / clears the in-flight flag
around each tool dispatch.

## File conflicts

Per-file diff prompting isn't wired in T3-03 — SnapshotStore's
restore is all-or-nothing today. The safety guarantee comes from
the pre-rollback checkpoint instead: any externally-modified file
captured in it can be recovered by rolling forward again.

A richer per-file prompt is a follow-up; the slash command's
`on_file_conflict` parameter is reserved for it.

## What rollback can't do

- Un-send Telegram / Discord / email messages.
- Un-call external APIs.
- Undo work performed by external services.

Only athena's own state — the session log, the workspace files
that went through tracked write paths, the skill catalogue, the
profile's memory entries — is reverted. The audit log makes
external-side-effect chatter visible so you know what *wasn't*
revertible.

## Storage layout

```
<profile_dir>/checkpoints/<session_id>/
    cp-<id>.json           # per-checkpoint record
    audit.jsonl            # checkpoint + rollback events
    state/
        skills/<token>/    # captured skill manifests
        memory/<token>/    # captured memory manifests
```

File-snapshot tarballs live under the existing
`<profile_dir>/snapshots/YYYY/MM/DD/` tree managed by
`SnapshotStore`, content-addressed and shared across checkpoints.

## Configuration

No explicit config block — checkpoints follow the active profile.
Pre-rollback entries are not auto-pruned; run
`athena checkpoint purge` (or `/checkpoints purge`) when you want
to drop them.

## Limitations

- File-conflict prompting is reserved (see above).
- Fork sessions don't have a checkpoint manager — checkpoints
  belong to the parent foreground session.
- The session JSONL truncation does not rebuild the SQLite session
  index automatically. Run `athena reindex` to rebuild if the
  index matters to you (the JSONL is the truth-of-record either
  way).
