# Auto kanban — the persisted task board

Athena's `TaskCreate` / `TaskUpdate` / `TaskList` tools now sit
on top of a persisted store, and the same store renders as a
kanban board. The agent maintains it as a side effect of
working — you don't curate it.

## What it is

| Surface | What it does |
|---|---|
| `TaskCreate` / `TaskUpdate` / `TaskList` tools | The agent's existing multi-step planning surface. **API is unchanged**; only persistence is added. |
| `board_show` tool | Returns the kanban columns as structured JSON for the model. |
| `athena board` CLI | Static (or TUI) render of the same columns. |
| `/board` slash | In-session display of the columns. |
| `/subgoal <text>` (T5-07) | Projects into the same store as a card with `goal_id` set. |

There is **one backing store** for tasks AND goal subgoals.
That's the design's load-bearing invariant — no parallel lists,
no drift between the board and the goal's view of subgoals.

## Status vocabulary

| Tool surface (Claude Code style) | Internal / board column |
|---|---|
| `pending`     | `todo` |
| `in_progress` | `doing` |
| (none today)  | `blocked` (board only) |
| `completed`   | `done` |
| `deleted`     | (row removed) |

The mapping is at the tool boundary — the agent keeps using
`pending` / `in_progress` / `completed`; the board reads the
canonical names.

Board column order (left → right):

```
TODO → DOING → BLOCKED → DONE
```

## The store

Persisted JSON at `cfg.task_store_path` (default
`<profile_dir>/tasks/tasks.json`). Atomic-replace writes via
`athena.safety.secure_files` so a crash mid-write doesn't
truncate the store.

Per-row schema:

```json
{
  "id": "t-<uuid12>",
  "title": "implement feature",
  "status": "todo",
  "order": 0,
  "parent_id": null,
  "goal_id": null,
  "session_id": null,
  "workspace": "/path/to/repo",
  "note": "optional detail / activeForm",
  "created_at": 1234567890.0,
  "updated_at": 1234567890.0
}
```

`workspace` is auto-tagged at create time from the agent's
file_ops workspace. The board's default view filters by the
active workspace so project A's tasks don't show in project B's
REPL.

`goal_id` distinguishes a regular task (`null`) from a
goal-loop subgoal (`g-<uuid12>`). The board can filter to a
single goal's cards.

## Status moves a card

```text
TaskCreate(subject="...") → row goes to TODO at the end
TaskUpdate(taskId=X, status="in_progress") → moves to DOING
TaskUpdate(taskId=X, status="completed")   → moves to DONE
TaskUpdate(taskId=X, status="deleted")     → row removed
```

`status` change re-orders to the END of the new column.
`order` within a column is explicit on each row — stable
across reloads + ready for future drag-equivalent reordering.

## The board view

### `athena board` CLI

```bash
athena board              # static or TUI (auto-detect)
athena board --static     # force the plain text render
athena board --goal G     # filter to one goal's cards
athena board --profile P  # render a non-default profile's board
```

Plain (always works, no deps):

```text
board · workspace: /home/me/proj  store: …/tasks.json
TODO (2)  DOING (1)  BLOCKED (0)  DONE (3)

TODO
  • implement feature X       t-abc123def456
        defines the user-visible behaviour
  • write tests               t-def789abc012 🎯

DOING
  • refactor module Y         t-321fedcba654

DONE
  • update changelog          t-789abcdef012
  • ship v0.5                 t-456789abcdef
  • add board command         t-cdef89012345 🎯
```

The 🎯 marks goal-linked cards (subgoals from an active
`/goal`).

The interactive **TUI** lights up automatically when:

1. `stdout` is a TTY, AND
2. `textual` is installed (the optional `athena[board]` extra).

When `textual` isn't installed, the CLI falls back to the
static render — no error, no missing-dep noise. Install with
`pip install athena-agent[board]` to enable the TUI.

### `board_show` tool

The model-callable surface. Returns JSON the agent can read
during a goal run to know what's left:

```json
{
  "workspace": "/home/me/proj",
  "goal_id": null,
  "counts": {"todo": 2, "doing": 1, "blocked": 0, "done": 3},
  "columns": {
    "todo":    [{"id": "t-…", "title": "…", "goal_id": null, ...}, ...],
    "doing":   [...],
    "blocked": [],
    "done":    [...]
  }
}
```

Every column is present, even when empty. The card shape is
identical between the tool's JSON and the CLI's render —
they're the same projection function.

## The single-store invariant

**Tasks and goal subgoals live in the same JSON file.**
The only difference is `goal_id`:

- `TaskCreate(subject="X")` → `Task(title="X", goal_id=null)`
- `/subgoal Y` (inside an active `/goal`) → `Task(title="Y", goal_id="g-…")`

The board's default workspace view shows both shapes; the
goal-filtered view (`athena board --goal g-…` or
`board_show(goal_id="g-…")`) isolates the subgoals.

This means:

- **The board and the goal's view of subgoals can never
  disagree.** They're the same data.
- **A subgoal completed via `/subgoal done` shows as a done
  card on the board immediately** — the same write hit both
  surfaces.
- **`/goal clear` removes that goal's subgoal-cards from the
  board** — no stale cards accumulate when you switch goals.

## Auto-maintain (board_auto_maintain)

`cfg.board_auto_maintain = true` (default) appends a short
section to the agent's system prompt nudging the agent to:

- `TaskCreate` when it decides on a multi-step plan
- `TaskUpdate(status="in_progress")` when it starts a task
- `TaskUpdate(status="completed")` as soon as the work is
  fully done (don't batch)

The board shines on autonomous goal runs (T5-07): the agent
keeps the board live as it works, the user can see what's
left at any time without interrupting the loop. Set
`board_auto_maintain = false` to turn the nudge off — the
agent will still use the tools when it wants to, just not
proactively.

## Archiving

`cfg.task_archive_done_after_days = 30.0` (default) controls
when stale done tasks roll off the board. `TaskStore.archive_done`
is a method, not an automatic process — call it explicitly
(or wire it into a session-start hook).

`older_than_days <= 0` is a no-op (don't accidentally archive
everything by passing 0).

The archive is in-memory only in v1 — done tasks past the
threshold simply disappear from the board on the next archive
sweep. Their record lives in athena's session JSONL / audit
log; the board doesn't try to be the canonical "what did I do
last week" surface.

## Configuration

```toml
# Persistence + storage
task_persist                 = true
task_store_path              = "/path/to/tasks.json"  # default <profile_dir>/tasks/tasks.json

# Auto-maintain nudge in the system prompt
board_auto_maintain          = true

# Archive threshold for archive_done()
task_archive_done_after_days = 30.0
```

## Workspace + profile scoping

- **Workspace** is auto-tagged at create time. `athena board`
  (and the in-session `/board`) filter to the active
  workspace by default. Use `--goal` to additionally filter to
  a specific goal's cards.
- **Profile** lives in the path (`<profile_dir>/tasks/tasks.json`).
  Different profiles → different boards. Switch profiles to
  switch boards.

## What the board does not do

- **Doesn't sync to anything external.** No GitHub Issues, no
  Linear, no JIRA integration. The store is local-only.
- **Doesn't enforce ordering.** Cards live in a column with an
  explicit `order`; the agent doesn't auto-reorder by priority.
  A future surface (`TaskReorder(id, position)`) would land if
  the use case appears.
- **Doesn't enforce subgoal-completion order.** Subgoals are
  advisory breadcrumbs — the model can address them in any
  order; `/subgoal done` just flips the first not-done one.
- **Doesn't add a `blocked` tool surface.** The `blocked`
  column exists in the store + the board so future surfaces /
  manual edits can use it, but `TaskUpdate` today still uses
  the legacy `pending|in_progress|completed|deleted` enum.

## Smoke

```bash
athena board                  # empty board for the workspace
# in athena:
athena
> /goal build a CLI flag parser with tests
  > /subgoal define the flag schema
  > /subgoal parse argv
  > /subgoal write tests
  # as the agent works, cards move todo→doing→done automatically
  # — TaskUpdate calls from inside the goal-loop drive the moves
athena board                  # shows live columns; persists across restart
```

## Related

- [`/goal` continuation loop](goal.md) — subgoals project into
  the same store; the board is the live view of an autonomous
  goal run
- [Tools registry](tool-registry.md) — `TaskCreate` /
  `TaskUpdate` / `TaskList` / `board_show`
