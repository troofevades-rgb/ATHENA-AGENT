# `athena batch` — batch runner

Iterates the T7-01 headless primitive over a JSONL of tasks. Per-run envelopes land on disk; a batch manifest aggregates the results. The engine under cron jobs, the Phase 7 training-loop trajectory generator, and the future T7-03 eval-battery.

```bash
athena batch tasks.jsonl                            # serial; output → <profile>/batch/<batch_id>/
athena batch tasks.jsonl -j 4                       # 4 concurrent workers
athena batch tasks.jsonl -o ./out --force           # custom output dir + re-run existing
athena batch tasks.jsonl --json | jq                # final manifest to stdout
```

## Input format

JSONL — one task per line. Blank lines and lines starting with `#` are ignored (comment shebang allowed):

```jsonl
# tasks for the nightly trajectory run
{"task": "refactor athena/agent/fork.py to drop the daemon-thread tag"}
{"task": "add a docstring to athena/headless/runner.py:run_headless", "run_id": "doc-fix-001"}
{"task": "write tests for the new helper", "cwd": "/abs/project", "timeout_s": 600, "model": "claude-sonnet-4-6"}
```

| Field | Required | Default |
|---|---|---|
| `task` | yes | — |
| `run_id` | no | auto-minted `r-<uuid12>` |
| `cwd` | no | the batch's `-C` / `--cwd` (else `$PWD`) |
| `timeout_s` | no | none (no wall-clock cap) |
| `model` | no | `cfg.model` |

Extra keys are tolerated (forward-compat).

## Output

```
<output_dir>/
├── manifest.json           # aggregated outcome
├── r-001.json              # per-run envelope (T7-01 RunResult shape)
├── r-002.json
└── ...
```

Each per-run JSON file is the T7-01 envelope verbatim — same shape `athena -p ... --json` emits. Already-existing files are **skipped by default** (resume-safe).

The manifest:

```json
{
  "batch_id": "b-abc123def456",
  "started_at": "2026-05-21T...",
  "finished_at": "2026-05-21T...",
  "duration_s": 142.7,
  "output_dir": "/abs/path/.athena/batch/b-abc...",
  "total": 50,
  "completed": 47,
  "skipped": 3,
  "by_status": {"ok": 45, "error": 2, "timeout": 0, "interrupted": 0},
  "entries": [
    {"run_id": "r-001", "status": "ok", "exit_code": 0,
     "duration_s": 1.2, "task_excerpt": "...",
     "envelope_path": ".../r-001.json"},
    ...
  ]
}
```

`entries` is in **input JSONL line order**, regardless of completion order — even with `--parallel 4`. Stable batch output is what makes diffing two runs of the same input set useful.

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | every entry ended `ok` (or skipped — resume scenarios) |
| 1 | one or more entries ended `error` / `timeout` / `interrupted` / `invalid` |
| 2 | input validation failed BEFORE any work fired (missing file, bad JSON, missing task field) |

So `athena batch ... && deploy.sh` works in CI: the deploy fires only when every batched task succeeded.

## Composition recipes

### Generate training trajectories overnight

```bash
# Generate a tasks file from your eval corpus.
jq -c '{task}' eval_corpus.jsonl > tasks.jsonl

# Run them all overnight with 4 workers.
athena batch tasks.jsonl -j 4 --output-dir nightly-$(date +%Y%m%d) --quiet --json > nightly.manifest

# Pipe the manifest into the training-loop labeling tool.
jq -r '.entries[] | select(.status == "ok") | .envelope_path' nightly.manifest \
  | xargs athena train review
```

### Cron-driven nightly run

```toml
# ~/.athena/cron.toml
[[jobs]]
schedule = "0 2 * * *"   # 2am daily
command = "athena batch /home/me/athena-tasks/nightly.jsonl --quiet --output-dir /home/me/athena-batches/$(date +%%Y%%m%%d)"
```

### Eval battery (proto-T7-03)

```bash
# tasks.jsonl — one labeled case per line
# Each line carries {task, run_id, expected (custom field)} — extras are tolerated
athena batch eval_cases.jsonl --output-dir eval-out

# Score each result against its expected.
for env in eval-out/r-*.json; do
  rid=$(jq -r .run_id "$env")
  actual=$(jq -r .assistant_text "$env")
  expected=$(jq --arg rid "$rid" 'select(.run_id == $rid) | .expected' eval_cases.jsonl)
  ./score.py --run-id "$rid" --actual "$actual" --expected "$expected"
done | tee scores.txt
```

T7-03 will wrap that loop into one tool; the primitive is ready now.

### Resume after interrupt

If a batch gets Ctrl+C'd or the machine reboots, the manifest reflects what happened. Re-running with the **same output-dir** picks up only the un-finished entries:

```bash
# First run — interrupted at entry 17/50.
athena batch tasks.jsonl --output-dir b-2026-05-21

# Re-run — entries 1..16 skipped (envelopes already on disk), 17..50 run fresh.
athena batch tasks.jsonl --output-dir b-2026-05-21

# Force-rerun everything (e.g. after upgrading the model).
athena batch tasks.jsonl --output-dir b-2026-05-21 --force
```

## Concurrency model

`--parallel N` spawns N workers via `ThreadPoolExecutor`. Each worker:

- Constructs its own `Agent` inside `run_headless` (no shared state — distinct `session_id`, distinct browser context, distinct approval ContextVar).
- Reads from the SAME provider credential pool, the SAME cross-session cache, the SAME audit logs (all thread-safe at the athena level).

Workers may finish in any order; the manifest is re-sorted to input order before write. A worker that gets a timeout / interrupt / approval-denied error still ends cleanly — just records `status=timeout|interrupted|invalid` in its envelope. Other workers keep running.

`--parallel 1` (default) is serial — safest, and the right choice for batches where one task's side effects might influence the next (e.g. multi-step refactors that build on each other).

## What's NOT in this phase

- **Per-entry dependencies.** Every entry is independent. A batch with "step 1 → step 2" semantics needs to be one task with internal steps, not two batch entries.
- **Stream-out batched envelopes.** The manifest lands at end-of-batch (and on interrupt). For real-time per-run observation, tail the stderr progress or watch the output dir.
- **Cost gating.** No "stop the batch if cost exceeds N" knob yet. The per-run envelope carries `cost_est`; a wrapper script can check + abort if needed.
- **Distributed batch.** Single-machine ThreadPoolExecutor only. Multi-machine fan-out is a future phase.

## Test layout

`tests/batch/test_runner.py` (23) — engine: `parse_tasks_file` accepts blanks + comments, rejects bad JSON with line numbers; `_safe_filename` never escapes; happy path writes envelopes + manifest; per-entry overrides propagate; status histogram aggregates; resume-safety skips existing + `force=True` reruns; progress fires per entry including skipped; minted vs supplied batch_id; empty batch writes empty manifest; long task/error excerpts truncated.

`tests/batch/test_cli.py` (14) — full CLI surface: validation exit codes (2 for missing file / bad JSON; 0 for empty file); serial happy path writes envelopes + manifest; default output-dir under profile; `--json` single-line manifest on stdout; resume-safety + `--force`; exit 1 on any entry failure; exit 0 on all-skipped batch; parallel run completes in input order with all envelopes written; stderr progress lines emitted by default + suppressed with `--quiet`.

## Reference

- Core engine: `athena/batch/runner.py`
- Manifest dataclasses: `athena/batch/manifest.py`
- CLI: `athena/cli/batch.py`
- Headless primitive (T7-01) that batch iterates: `docs/reference/headless.md`
- Future: T7-03 eval-battery (formalised pipeline)
