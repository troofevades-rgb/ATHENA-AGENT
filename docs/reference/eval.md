# `athena eval` — eval battery

Runs a labeled case set through athena's batch + scoring pipeline. Pass/fail per case + an aggregate summary + (optional) regression diff against a baseline. **Closes the trio T7-01 / T7-02 / T7-03.**

```bash
athena eval cases.jsonl                                # default: exact scorer
athena eval cases.jsonl --scorer contains              # CLI default scorer
athena eval cases.jsonl --baseline ./last/             # regression diff
athena eval cases.jsonl --json | jq .pass_rate         # CI gate
```

## Input format

JSONL — one case per line. Required fields: `task` + `expected`. Optional: `case_id`, `scorer` (per-case override), `cwd`, `timeout_s`, `model`. Blank lines + `#` comments ignored.

```jsonl
# arithmetic
{"task": "what is 2+2?", "expected": "4", "case_id": "math-001"}
{"task": "what is 3*5?", "expected": "15", "case_id": "math-002"}

# a per-case scorer override + a structured JSON case
{"task": "list 3 colors as a JSON array",
 "expected": {"path": "[0]", "value": "red"},
 "case_id": "json-001",
 "scorer": "json_path"}

# regex-based with inline flags
{"task": "what year did the moon landing happen?",
 "expected": "(?i)\\b1969\\b",
 "case_id": "history-001",
 "scorer": "regex"}

# longer-running case
{"task": "refactor the foo module to use type hints",
 "expected": "type hint",
 "case_id": "refactor-001",
 "scorer": "contains",
 "timeout_s": 300,
 "cwd": "/abs/path/to/repo"}
```

Extra keys are tolerated and preserved into the scorer's `context` dict — custom scorers can read off categories, difficulty tags, etc.

## Built-in scorers

| Name | Expected shape | Pass condition |
|---|---|---|
| `exact` | `string` | `actual.strip() == expected.strip()` (strict, case-sensitive) |
| `contains` | `string` | `expected in actual` |
| `regex` | `string` (a pattern) | `re.search(pattern, actual)` matches; inline flags supported (e.g. `(?i)hello`) |
| `json_path` | `{"path": "<dotted>", "value": <expected>}` | `json.loads(actual)[path] == value`; dotted paths with `[N]` indices: `data.users[0].id` |

Custom scorers register at import time via `athena.eval.scorers.register_scorer`. Once registered, they're addressable from `--scorer NAME` and per-case `scorer` fields.

## Output

```
<output_dir>/
├── eval-summary.json     # aggregate (this is the CI artifact)
├── scores.jsonl          # one EvalScore per case
├── manifest.json         # the underlying batch's manifest
├── <case-id-1>.json      # per-run envelope (the T7-01 shape)
├── <case-id-2>.json
└── ...
```

Default `<output_dir>` is `<profile_dir>/eval/<eval_id>/`. Override with `-o DIR`.

**`eval-summary.json`** (the artifact CI gates branch on):

```json
{
  "eval_id": "v-abc123def456",
  "batch_id": "b-...",
  "started_at": "...",
  "finished_at": "...",
  "duration_s": 142.7,
  "output_dir": "/abs/path/.athena/eval/v-...",
  "total": 50,
  "passed": 47,
  "failed": 2,
  "errored": 1,
  "pass_rate": 0.94,
  "avg_score": 0.94,
  "by_scorer": {
    "exact":     {"total": 30, "passed": 28, "failed": 2, "errored": 0},
    "contains":  {"total": 15, "passed": 15, "failed": 0, "errored": 0},
    "json_path": {"total":  5, "passed":  4, "failed": 0, "errored": 1}
  },
  "baseline_id": "v-prior-run",      // only present when --baseline DIR set
  "regressions": ["math-007"],       // case_ids that passed in baseline, fail now
  "improvements": ["history-003"],   // case_ids that failed in baseline, pass now
  "cases": [
    {"case_id": "math-001", "passed": true, "scorer": "exact",
     "score": 1.0, "details": "exact match", ...},
    ...
  ]
}
```

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | Every case passed |
| 1 | One or more cases failed OR errored (model didn't complete) |
| 2 | Validation failed BEFORE any case ran (missing file, bad JSON, unknown `--scorer`, etc.) |

`athena eval cases.jsonl && ./deploy.sh` is reliable in CI.

## Three failure categories

A case can end up in one of three buckets, and the distinction matters for diagnosis:

- **`passed`**: scorer returned `passed=True`. The model did the right thing.
- **`failed`**: model returned `status=ok` but the scorer returned `passed=False`. The model answered, but not correctly. **Investigate the answer.**
- **`errored`**: model didn't complete — `status` was `error` / `timeout` / `interrupted` / `invalid`. The scorer wasn't even invoked. **Investigate why the run didn't complete** (model unreachable, timeout too short, etc.); fixing this is upstream of fixing scoring.

The summary surfaces all three counts separately so you don't conflate "the model gave a bad answer" with "the model didn't respond at all."

## Baseline regression diff

`--baseline DIR` loads `DIR/eval-summary.json` and joins on `case_id`:

- **Regressions**: cases that PASSED in the baseline + FAILED (or errored) in the current run.
- **Improvements**: cases that FAILED (or errored) in the baseline + PASS in the current run.

Cases that don't appear in both runs are silently excluded (no phantom regressions/improvements). For stable diffs across runs, **set explicit `case_id` values in your JSONL** — auto-minted ones change each invocation.

Use this to gate model upgrades:

```bash
# Train a new tag.
athena train review && athena train build my-new-tag

# Run the eval against the new tag (passes --model down to batch).
athena eval cases.jsonl --model my-new-tag --output-dir ./eval-new \
    --baseline ./eval-prior --json | tee result.json

# CI gates on regressions: any → fail.
if [ "$(jq '.regressions | length' result.json)" -gt 0 ]; then
  echo "regressions detected; not promoting"
  exit 1
fi
```

## Composition recipes

### CI gate — block PR merges on any regression

```yaml
# .github/workflows/eval.yml
- name: Run eval against baseline
  run: |
    athena eval ci_cases.jsonl \
      --output-dir ./eval-current \
      --baseline ./eval-baseline \
      --json | tee eval.json
    test "$(jq '.regressions | length' eval.json)" -eq 0
```

### Sweep across models — same cases, different `--model`

```bash
for model in old new candidate; do
  athena eval cases.jsonl --model "$model" \
    --output-dir "eval-runs/$model" --quiet
done

# Then diff each against the baseline.
for model in new candidate; do
  athena eval cases.jsonl --model "$model" \
    --output-dir "eval-runs/$model-vs-old" \
    --baseline "eval-runs/old" --quiet
done
```

### Training-loop integration (the closed-loop gate)

```bash
athena train review                          # interactive labeling
athena train build my-trained-model           # produce a new tag
athena eval cases.jsonl --model my-trained-model \
  --baseline ./eval-prior --json | tee eval.json

# Promote only if regressions == 0 and pass_rate ≥ 0.90.
if [ "$(jq '.regressions | length' eval.json)" -eq 0 ] \
   && (( $(jq '.pass_rate' eval.json | awk '{print ($1 >= 0.90)}') )); then
  athena model switch my-trained-model
fi
```

That's the closed training loop fully testable head-to-head.

### Iterate on a scorer without re-running the model

Re-running an eval over the same output_dir is **resume-safe**: the per-run envelopes are reused, and only the scoring pass runs again. So iterating on a custom scorer is cheap:

```bash
# First run — uses the new scorer; downloads model answers.
athena eval cases.jsonl --output-dir ./out

# Edit the scorer module. Re-run — model answers reused from
# disk, scorer re-evaluates them.
athena eval cases.jsonl --output-dir ./out
```

`--force` overrides resume-safety + re-runs the model.

## Writing a custom scorer

```python
# my_scorers.py
from athena.eval.scorers import Score, register_scorer

def length_check(actual, expected, *, context):
    """Pass if actual length is within ±10% of expected length."""
    target = int(expected)
    actual_len = len(actual or "")
    ratio = actual_len / max(1, target)
    if 0.9 <= ratio <= 1.1:
        return Score(passed=True, score=1.0,
                     details=f"len {actual_len} within ±10% of {target}")
    return Score(passed=False, score=ratio,
                 details=f"len {actual_len} differs from {target} (ratio {ratio:.2f})")

register_scorer("length_check", length_check)
```

Then in your cases JSONL:

```jsonl
{"task": "write a haiku", "expected": 75, "scorer": "length_check"}
```

Athena imports `my_scorers` once (e.g. via a plugin or by adding it to your project) and the scorer becomes addressable.

## Test layout

`tests/eval/test_scorers.py` (42) — scorer Protocol + registry + 4 built-in scorers + Score / EvalCase / EvalScore / EvalSummary dataclasses + mint helpers + excerpt utility.

`tests/eval/test_runner.py` (18) — `run_eval` composition: parse_cases_file with line-numbered errors; all-pass / mixed / errored-counted-separately; per-case scorer override; json_path end-to-end; by_scorer histogram; case-id minting; baseline regression detection (passed→failed flip) + improvement detection (failed→passed flip) + missing baseline summary handled cleanly + unmatched case_ids don't generate phantoms; progress callback fires per case; empty cases produces empty summary with files written; unknown default scorer rejected up front.

`tests/eval/test_cli.py` (14) — full CLI plumbing: missing file → exit 2; unknown `--scorer` → exit 2 with "available scorers" list; bad JSON → exit 2 with line number; empty file → exit 0 with empty summary; all-pass → exit 0 with summary line; any-failure → exit 1; errored counted separately; `--json` single-line on stdout; default output-dir under `<profile>/eval/<eval_id>/`; baseline diff surfaces regressions + improvements on stderr; baseline missing-summary handled cleanly; per-case scorer override flows through; quiet mode suppresses progress but keeps the summary line.

## Reference

- Scorers: `athena/eval/scorers.py`
- Dataclasses: `athena/eval/summary.py`
- Runner: `athena/eval/runner.py`
- CLI: `athena/cli/eval.py`
- Composed primitives: `docs/reference/headless.md` (T7-01) + `docs/reference/batch.md` (T7-02)
