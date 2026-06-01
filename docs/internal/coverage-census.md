# Coverage Census — athena/ subpackages

Snapshot generated 2026-06-01 via `pytest --cov=athena --cov-report=json`.
Repo-wide total: **80% line coverage** (28,246 of 35,320 statements covered).

This census exists to test a specific concern raised in the external code
review (`MEMORY.md → project-consolidation-pass`):

> Suspected stub/aspirational subpackages: proxy/, sandbox/, verify/,
> user_model/, headless/

The data does NOT support that concern. Every subpackage flagged as "suspect"
has substantial coverage:

| Suspect package | Coverage | Disposition |
|---|---|---|
| `sandbox/` | 97.9% | Fully tested, load-bearing |
| `verify/` | 94.4% | Fully tested, load-bearing |
| `user_model/` | 93.1% | Fully tested, load-bearing |
| `proxy/` | 90.5% | Fully tested, load-bearing |
| `headless/` | 85.8% | Well-tested, load-bearing |

**Conclusion on the suspect-subpackages thesis:** all five are
test-backed at a higher rate than several core subpackages. They are NOT
stubs and should NOT be candidates for pruning purely on the "looks
aspirational" heuristic. If consolidation work targets these, it should be
on architectural / cohesion grounds, not on the assumption they're unused.

---

## All subpackages, ranked by coverage (ascending)

| Package | Coverage | Covered / Total | Notes |
|---|---|---|---|
| `eval/` | **43.1%** | 573 / 1,329 | LOWEST — eval harness entry points; integration tests would help |
| `cli/` | **60.8%** | 2,388 / 3,929 | CLI subcommands; argparse / `--help` paths hard to test fully |
| `audio/` | 70.4% | 205 / 291 | Transcription tooling; some backend code paths untestable without creds |
| `mcp/` | 73.1% | 1,056 / 1,444 | MCP client + transport; HTTP/SSE + OAuth less covered than stdio |
| `lsp/` | 73.3% | 173 / 236 | Language-server adapters; per-server quirks |
| `tools/` | 73.4% | 1,504 / 2,048 | Core agent tool surface — ⚠️ 26% uncovered worth examining |
| `social/` | 73.7% | 244 / 331 | Social-routing / X-API surfaces |
| `ocr/` | 74.4% | 151 / 203 | OCR pipeline |
| `document/` | 75.6% | 316 / 418 | Document parsing helpers |
| `tui_gateway/` | 76.5% | 919 / 1,202 | TUI ↔ Python bridge |
| `delegate/` | 76.7% | 158 / 206 | CLI delegation surface |
| `browser/` | 79.4% | 255 / 321 | Browser automation |
| `gateway/` | 80.3% | 2,077 / 2,586 | Messaging-platform daemon |
| `computer/` | 81.4% | 783 / 962 | Computer-use tools |
| `video/` | 82.1% | 316 / 385 | Video analyze pipeline |
| `acp/` | 82.6% | 371 / 449 | Agent Client Protocol server |
| `agent/` | 83.0% | 1,772 / 2,135 | Core run-turn loop |
| `commands/` | 83.4% | 1,736 / 2,082 | Slash commands |
| `update/` | 83.4% | 286 / 343 | Self-update |
| `athena/` (top-level) | 83.9% | 1,400 / 1,668 | Top-level modules (config, env, ui, etc.) |
| `headless/` | 85.8% | 109 / 127 | Headless one-shot runner |
| `vision/` | 86.7% | 409 / 472 | Vision analyze |
| `plugins/` | 86.9% | 595 / 685 | Plugin framework |
| `batch/` | 87.6% | 155 / 177 | Batch runner |
| `curator/` | 88.6% | 395 / 446 | 7-day consolidator |
| `skills/` | 89.2% | 881 / 988 | File-based skill format |
| `sessions/` | 89.8% | 326 / 363 | JSONL + SQLite |
| `recall/` | 89.9% | 249 / 277 | Vector recall |
| `transform/` | 89.9% | 1,109 / 1,233 | Training loop |
| `audit/` | 90.0% | 367 / 408 | Mutation audit log |
| `webhooks/` | 90.4% | 412 / 456 | HTTP webhook listener |
| `proxy/` | 90.5% | 400 / 442 | Proxy surfaces |
| `providers/` | 90.8% | 2,052 / 2,261 | Provider abstraction (multi-vendor) |
| `safety/` | 90.8% | 896 / 987 | Safety/provenance subsystem |
| `videogen/` | 91.4% | 403 / 441 | Video generation |
| `migration/` | 91.7% | 442 / 482 | Hermes import |
| `cron/` | 91.9% | 352 / 383 | APScheduler-backed jobs |
| `memory/` | 92.5% | 259 / 280 | Persistent memory |
| `prompts/` | 92.9% | 130 / 140 | System-prompt builder |
| `jailbreak/` | 93.0% | 240 / 258 | Godmode toolkit |
| `user_model/` | 93.1% | 217 / 233 | User-model tracking |
| `review/` | 94.1% | 95 / 101 | Background review fork |
| `tasks/` | 94.4% | 186 / 197 | Task store |
| `verify/` | 94.4% | 187 / 198 | Verification subsystem |
| `profiles/` | 95.5% | 193 / 202 | Multi-profile isolation |
| `goal/` | 97.2% | 240 / 247 | Ralph-loop driver |
| `sandbox/` | 97.9% | 92 / 94 | Sandboxing utilities |
| `cache/` | 98.1% | 101 / 103 | Cross-session cache |
| `media/` | 100% | 43 / 43 | Media helpers |
| `steer/` | 100% | 28 / 28 | Steer queue |

---

## Actionable subset (coverage < 75%)

These six subpackages are the ones where additional tests would give the
biggest correctness uplift. None are dead code; they're under-tested
relative to the rest of the codebase.

### 1. `eval/` (43.1%) — Highest priority

776 uncovered statements out of 1,329. The eval harness has lots of
glue code (run loaders, scoring backends, dataset builders). Suggested
focus areas:

- The trajectory-extraction and dataset-assembly path
- Score-aggregation across model families
- Race / autoscore orchestration (touches multiple providers)

A focused integration test that runs one eval end-to-end against a stub
provider would close significant gaps.

### 2. `cli/` (60.8%) — Second priority

1,541 uncovered statements. Many one-off `argparse` paths. The high-
value gaps are in:

- `cli/train.py` — multi-step training subcommands
- `cli/cron.py` — schedule + daemon paths
- `cli/gateway.py` — daemon lifecycle

Subcommand `--help` rendering is usually testable cheaply.

### 3. `audio/` (70.4%), `mcp/` (73.1%), `lsp/` (73.3%)

These three sit at a similar level. For `mcp/` specifically, the gaps
are concentrated in the HTTP/SSE transport + OAuth flow — both newer
than the stdio path and harder to test without a real server.

### 4. `tools/` (73.4%) — Look here for hidden gaps

Core agent tool surface. 544 uncovered statements is a lot. Worth
spot-checking which tools are well-tested vs which slipped through.
Likely culprits: tools that wrap external SDKs (gemini image, web
fetch, etc.) where the integration surface is mocked but the post-
processing paths aren't.

---

## What this does NOT show

- **Branch coverage** — only line coverage. A 100%-line-covered module
  with a single un-exercised `else` branch reads as fully tested here.
- **Quality of tests** — a test that doesn't assert anything still
  increments coverage. The numbers above don't distinguish.
- **Integration vs unit** — many "covered" lines are exercised only
  via `from athena.X import Y` import-time evaluation, not actually
  asserted on.

For a more rigorous follow-up: re-run with `--cov-branch` and audit
the per-module reports for branch gaps.

---

## How to regenerate this report

```bash
pytest --cov=athena --cov-report=json:coverage.json -q --timeout=120
python -c "
import json
from collections import defaultdict
from pathlib import Path
data = json.load(open('coverage.json'))
by_pkg = defaultdict(lambda: [0, 0])
for path, info in data['files'].items():
    p = Path(path)
    parts = p.parts
    if parts[0] != 'athena':
        continue
    pkg = '/'.join(parts[:2]) if len(parts) >= 3 and not parts[1].endswith('.py') else 'athena (top-level)'
    s = info['summary']
    by_pkg[pkg][0] += s['covered_lines']
    by_pkg[pkg][1] += s['num_statements']
rows = sorted((c/t*100 if t else 0, pkg, c, t) for pkg, (c, t) in by_pkg.items())
for pct, pkg, c, t in rows:
    print(f'{pct:>6.1f} {c:>8} {t:>8}  {pkg}')
"
```

`coverage.json` is gitignored — regenerate fresh each time.
