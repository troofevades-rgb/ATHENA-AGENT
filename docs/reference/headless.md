# Headless run primitive

`athena -p "<task>"` was always a one-shot path. T7-01 turns it into the **engine under batch runners, cron jobs, gateway dispatchers, and (future) eval harnesses** by adding the things a programmatic caller actually needs:

| Flag | What it does |
|---|---|
| `--json` | Emit a structured envelope on stdout; route TTY chatter to stderr |
| `--run-id <id>` | Operator-supplied correlation key (auto-minted otherwise) |
| `--timeout SECONDS` | Wall-clock cap; expires gracefully → exit 124 |
| `--task FILE` | Read the prompt from a file (alt. to `-p` for long / shell-unfriendly strings) |

Existing `athena -p "<task>"` invocations keep working unchanged — the new behavior is opt-in.

## Exit codes

Stable POSIX mapping across modes:

| Code | Status | Meaning |
|---:|---|---|
| 0   | `ok`           | Run completed successfully |
| 1   | `error`        | Generic error (agent crashed, model unreachable, run_turn raised) |
| 2   | `invalid`      | Bad input (missing required arg, workspace doesn't exist, malformed `--task` file) |
| 124 | `timeout`      | Wall-clock timeout fired (matches `timeout(1)`) |
| 130 | `interrupted`  | SIGINT (Ctrl+C; matches `128 + SIGINT(2)`) |

A shell script can branch reliably:

```bash
athena -p "summarise CHANGELOG.md" --json > result.json
case $? in
  0)   echo "ok" ;;
  124) echo "timed out" ;;
  130) echo "user cancelled" ;;
  *)   echo "failed: $(jq -r .error result.json)" ;;
esac
```

## The `--json` envelope

Exactly one JSON document on stdout, ever — no partial output, no interleaving, no banner. TTY chatter (`ui.info` / `ui.warn` / `ui.error` / banner) routes to stderr so `subprocess.run(...).stdout` is always parser-friendly.

```json
{
  "run_id": "r-abc123def456",
  "status": "ok",
  "exit_code": 0,
  "started_at": "2026-05-21T14:23:01.234567Z",
  "finished_at": "2026-05-21T14:23:42.876543Z",
  "duration_s": 41.642,
  "task": "summarise the CHANGELOG",
  "workspace": "/abs/path/to/project",
  "model": "troofevades-q35:athena",
  "profile": "default",
  "session_id": "s-1234567890ab",
  "tool_calls": [
    {"name": "Read",   "count": 3},
    {"name": "Bash",   "count": 1}
  ],
  "tokens": {
    "prompt": 4521,
    "completion": 1834,
    "cache_read": 4200,
    "cache_creation": 321
  },
  "cost_est": 0.0,
  "assistant_text": "The CHANGELOG covers …",
  "error": null
}
```

| Field | Notes |
|---|---|
| `run_id` | Stable across the run; `r-<uuid12>` when minted, your value when passed via `--run-id`. |
| `status` | One of `ok` / `error` / `timeout` / `interrupted` / `invalid`. |
| `exit_code` | Pre-computed so a parser doesn't have to re-derive from status. |
| `session_id` | Athena's internal session ID (distinct from `run_id` — query the session JSONL with this). |
| `tool_calls` | `[{name, count}]` in descending-count order. |
| `tokens` | Prompt / completion / T2-01 prompt-cache read+creation counts. |
| `cost_est` | USD; `0.0` for local-only or unknown-pricing models. |
| `assistant_text` | Final assistant message, capped at 8000 chars with a truncation marker pointing at `session_id`. |
| `error` | Exception type + message OR structured reason; `null` on success. |

The envelope shape is **stable** — future additions go via new optional fields, never field removals.

## `--run-id` correlation

`run_id` is the **batch correlation key**, distinct from athena's internal `session_id`. The two live side-by-side in the envelope:

- `run_id` — the operator's correlation key (whatever you passed, or a minted `r-<uuid12>`)
- `session_id` — athena's session JSONL identifier (always `s-<uuid12>`)

For a batch runner: tag each entry with its `run_id` (e.g. `r-batch-2026-05-21-001`), and the envelope tells you both keys back. Query the audit log / session JSONL via `session_id`; aggregate the batch's CSV via `run_id`.

When not supplied, `run_id` is auto-minted with the same `r-<uuid12>` format so an operator can tell minted vs operator-supplied apart at a glance.

## `--timeout`

`--timeout 60` caps the run at 60 wall-clock seconds. On expiry:
- A `threading.Timer` fires `_thread.interrupt_main()` (the same path Ctrl+C uses)
- The agent's existing turn-cancel paths catch the interrupt
- The runner distinguishes timed-out from user-interrupted via a sentinel flag
- Result: `status=timeout`, `exit_code=124`, `error="wall-clock timeout after 60.0s"`

State is captured before exit — tool calls already fired, tokens consumed, partial assistant text all land in the envelope. A timed-out run is still useful telemetry.

## `--task FILE`

For long prompts, prompts with shell-unfriendly characters, or prompts checked into version control:

```bash
cat > prompts/summarise.txt <<'EOF'
Summarise the changes between the v0.2.0 tag and HEAD. Group by
subsystem (gateway / recall / curator / verify / etc.). Don't
include changes to test infrastructure.
EOF

athena --task prompts/summarise.txt --json --run-id "summary-$(date +%s)"
```

`--task` wins over `-p` when both are set, so a batch driver can override a default at the command line.

## Composition recipes

### One-off in a shell script

```bash
athena -p "$(< task.txt)" --json --timeout 300 > result.json
test $? -eq 0 || { echo "run failed"; exit 1; }
jq -r .assistant_text result.json
```

### Iterate over a list of tasks (proto-batch)

```bash
while IFS= read -r task; do
  athena -p "$task" --json --timeout 120 \
    --run-id "batch-$(date +%s)-$RANDOM" \
    >> batch_results.jsonl
done < tasks.txt
```

(T7-02 batch_runner will do this with proper concurrency + a manifest file. This is the manual version.)

### Cron job (the existing athena cron tool fires this)

```toml
# ~/.athena/cron.toml
[[jobs]]
schedule = "@daily"
command = """athena -p "review yesterday's commit log + flag anything suspicious" --json --timeout 600"""
```

### Pipe into an eval harness

```bash
for case in eval_cases/*.json; do
  task=$(jq -r .task "$case")
  expected=$(jq -r .expected "$case")
  result=$(athena -p "$task" --json --timeout 60)
  actual=$(jq -r .assistant_text <<< "$result")
  ./score.py --expected "$expected" --actual "$actual" \
             --run-id "$(jq -r .run_id <<< "$result")"
done
```

(T7-03 eval-battery will formalise this. The primitive is ready now.)

## What's NOT in this phase

- **Concurrent batch.** T7-02. The primitive serialises one run at a time.
- **Persistent batch manifest.** T7-02. Each `--json` invocation is independent.
- **Streaming envelope.** The envelope lands once at the end. Progress lives on stderr via the existing UI surfaces.
- **Resume on failure.** If a run times out / crashes / is killed, there's no auto-restart. The envelope tells you what happened; the caller decides what to do.
- **JSON parsing for arbitrary tool output.** The envelope's `assistant_text` is the final model message; per-tool details aren't broken out (that's what the audit log + session JSONL are for, keyed by `session_id`).

## Test layout

`tests/headless/test_result.py` (13) — exit-code mapping per status; JSON envelope shape; truncation marker for long assistant text; required keys present; single-line by default.

`tests/headless/test_runner.py` (16) — `run_headless` core paths via a stub Agent: success returns ok + populated stats; `run_id` minted vs passed-through; timestamps; validation rejects empty task / nonexistent workspace / non-directory workspace; agent exception → status=error with type+message; KeyboardInterrupt → status=interrupted; UI callback fires; `agent.close()` always called.

`tests/headless/test_cli.py` (12) — full CLI plumbing: new flags accepted; `--json` envelope single-line + parsable + nothing-else-on-stdout; `--task FILE` reads with quotes preserved; missing task file → invalid + exit 2 + valid JSON; `--task` wins over `-p`; `--json` without task → invalid; agent exception → exit 1 with structured envelope; legacy `-p` path returns 0 on success with NO JSON on stdout (backwards-compat).

## Reference

- Result envelope: `athena/headless/result.py`
- Runner: `athena/headless/runner.py`
- CLI integration: `athena/__main__.py` (`--json` / `--run-id` / `--timeout` / `--task`)
- Future: T7-02 batch_runner; T7-03 eval-battery
