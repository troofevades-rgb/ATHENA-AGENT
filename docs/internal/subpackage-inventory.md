# Subpackage Inventory — athena/

Generated 2026-06-01 by grepping `from athena.<pkg>` / `from ..<pkg>` across
the codebase and cross-referencing with the coverage census
(`docs/internal/coverage-census.md`).

Two questions this inventory answers:

1. **Is the package actually wired?** Coverage tells us if code is exercised
   by tests; import count tells us if it's reachable from another part of the
   live system.
2. **What's the consolidation surface?** Single-caller packages may indicate
   "should this have been a module of its caller instead of a peer package?"
   This is a discussion-starter, not a directive — small focused packages
   are fine, and the external review correctly noted athena is over-
   decomposed in places.

## Top-line finding

**No stub subpackages exist.** The external review (logged in
`MEMORY.md → project-consolidation-pass`) flagged proxy/, sandbox/,
verify/, user_model/, headless/ as "may be stubs or aspirational." The
data refutes this:

| Suspect | Coverage | External imports | Callers | Verdict |
|---|---|---|---|---|
| `proxy/` | 90.5% | 1 | cli | Real; wired through CLI subcommand |
| `sandbox/` | 97.9% | 4 | delegate, tools, verify | Real; multi-callee |
| `verify/` | 94.4% | 3 | cli, mcp, tools | Real; multi-callee |
| `user_model/` | 93.1% | 2 | commands, tools | Real; multi-callee |
| `headless/` | 85.8% | 2 | batch, cli | Real; multi-callee |

All five are above 85% covered and reachable from at least one caller.
None should be pruned on the "looks aspirational" heuristic.

---

## Inventory table

Sorted by import count (most heavily depended-on first). The `Callers`
column lists the immediate parent packages that import this one; it does
NOT recursively chase transitive use.

| Package | Coverage | External imports | Callers |
|---|---|---|---|
| `safety/` | 90.8% | 42 | acp, agent, audit, cli, computer (+12 more) |
| `providers/` | 90.8% | 41 | acp, agent, cache, cli, commands (+4 more) |
| `agent/` | 83.0% | 34 | acp, cli, commands, cron, curator (+8 more) |
| `tools/` | 73.4% | 34 | agent, audio, browser, cli, commands (+14 more) |
| `skills/` | 89.2% | 27 | agent, cli, commands, curator, mcp (+2 more) |
| `sessions/` | 89.8% | 15 | agent, cli, gateway, mcp, migration (+2 more) |
| `gateway/` | 80.3% | 14 | cli, cron, webhooks |
| `goal/` | 97.2% | 13 | acp, agent, commands, computer, prompts |
| `batch/` | 87.6% | 10 | cli, eval |
| `eval/` | 43.1% | 10 | cli |
| `jailbreak/` | 93.0% | 10 | commands |
| `memory/` | 92.5% | 10 | agent, cli, commands, mcp, profiles (+2 more) |
| `vision/` | 86.7% | 10 | audio, browser, computer, document, tools (+2 more) |
| `mcp/` | 73.1% | 9 | cli, commands |
| `transform/` | 89.9% | 9 | cli |
| `update/` | 83.4% | 9 | commands |
| `plugins/` | 86.9% | 7 | agent, cli, proxy |
| `profiles/` | 95.5% | 7 | agent, cli, webhooks |
| `media/` | 100% | 7 | audio, computer, mcp, ocr, recall (+2 more) |
| `recall/` | 89.9% | 6 | agent, cli, tools |
| `steer/` | 100% | 5 | acp, agent, commands |
| `tasks/` | 94.4% | 5 | commands, tools |
| `cron/` | 91.9% | 4 | cli |
| `curator/` | 88.6% | 4 | agent, cli |
| `sandbox/` | 97.9% | 4 | delegate, tools, verify |
| `tui_gateway/` | 76.5% | 4 | cli, commands, tools |
| `videogen/` | 91.4% | 4 | commands, providers, tools |
| `webhooks/` | 90.4% | 4 | cli, gateway |
| `browser/` | 79.4% | 3 | agent, tools |
| `cache/` | 98.1% | 3 | agent, cli |
| `cli/` | 60.8% | 3 | commands, cron |
| `computer/` | 81.4% | 3 | commands, tools |
| `social/` | 73.7% | 3 | providers, tools |
| `verify/` | 94.4% | 3 | cli, mcp, tools |
| `acp/` | 82.6% | 2 | cli |
| `audio/` | 70.4% | 2 | tools, video |
| `audit/` | 90.0% | 2 | cli |
| `delegate/` | 76.7% | 2 | cli, tools |
| `headless/` | 85.8% | 2 | batch, cli |
| `lsp/` | 73.3% | 2 | tools |
| `ocr/` | 74.4% | 2 | document, tools |
| `prompts/` | 92.9% | 2 | agent |
| `review/` | 94.1% | 2 | agent |
| `user_model/` | 93.1% | 2 | commands, tools |
| `document/` | 75.6% | 1 | tools |
| `migration/` | 91.7% | 1 | cli |
| `proxy/` | 90.5% | 1 | cli |
| `video/` | 82.1% | 1 | tools |
| `commands/` | 83.4% | 0 | (dispatched via @command registry) |

---

## Notable patterns

### Single-caller packages (1 import)

Four packages have only one external importer. These are NOT stubs —
they're well-tested — but they're candidates for consideration in a
cohesion sweep:

| Package | Caller | Coverage | Comment |
|---|---|---|---|
| `document/` | `tools/` | 75.6% | Document parsing helpers — could plausibly fold into `tools/document_*` modules |
| `migration/` | `cli/` | 91.7% | One-shot Hermes → athena migration — has its own CLI surface (`athena import-from-hermes`); keep separate |
| `proxy/` | `cli/` | 90.5% | OpenAI proxy server — exposed via `athena proxy` subcommand; keep separate (it's a daemon, has lifecycle) |
| `video/` | `tools/` | 82.1% | Video analyze tool wrapper — same observation as `document/`; could fold |

**Recommendation:** `document/` and `video/` are both invoked only from
`tools/` as tool implementations. They were initially flagged as fold
candidates, but **further investigation rules that out**:

- `document/` is 1146 LOC across 6 files (with an `extractors/` subpackage
  for format-specific pdf/docx code). Folding to a single `tools/document.py`
  would create a 1100+ LOC monster file and lose the format-extractor
  modularity.
- `video/` is 1331 LOC across 5 files (analyze, probe, extract, atoms).
  Same observation: each file owns a distinct responsibility (analyze vs
  metadata-probe vs frame-extract); folding loses that.

Both packages have appropriate internal modularity. The "1 caller"
inventory heuristic is a starting question, not a directive — it
correctly flagged them for review, but the answer is "leave them alone."

`migration/` and `proxy/` have their own CLI surfaces and lifecycles;
they're fine as separate packages even with a single caller.

### Zero external imports

`commands/` is imported by no other package. This is correct — slash
commands register via `@command` decorator and are dispatched through
the registry, not imported. The 0 import count here is by design.

### High-coverage, low-import (often internal utility)

`media/` (100% cov, 7 imports across 7 callers) is the model utility
pattern: small package, fully tested, imported by anyone who needs
media handling. `steer/` (100% cov, 5 imports across 3 callers) is
similar.

### Heavy hubs

Five packages (`safety`, `providers`, `agent`, `tools`, `skills`) each
have 27+ external imports. These are the load-bearing cores. Consolidation
work should NOT touch their import surfaces without an architectural
plan; their changeability ripples to every caller.

### `eval/` is the coverage outlier — but it's a testing-style mismatch, not a code problem

`eval/` has 10 external imports (substantial wiring) but only 43.1%
coverage on the headline. Drilling in: the gap is concentrated in
seven `agent/tasks/*.py` files (all 0%) which are DSL-like
SCENARIO definitions verified by running ``athena eval --task X``
against a real or stubbed model. The rest of `eval/` (runner,
scorers, summary, report, agent/runner, agent/report) sits at
67-100% covered.

These are appropriately-structured scenario specs measured against
a unit-test rubric. The fix is one end-to-end test that runs the
harness against a stub provider, not consolidation work. See
``coverage-census.md`` for the per-file breakdown.

---

## What the consolidation pass should target

Based on this inventory + the coverage census, the actionable surface
for a Karpathy-CLAUDE.md-style cleanup pass is:

1. **`eval/`** — Real, important. The "43.1% covered" headline is
   misleading; drill-in shows it's eval scenario definitions at 0%
   (verified by running ``athena eval``, not unit tests). The fix
   is one end-to-end harness test against a stub provider, NOT
   consolidation work.
2. ~~**`document/` and `video/`** — Candidates for folding into
   `tools/` as modules~~ — RULED OUT after deeper look. Both are
   1000+ LOC packages with appropriate internal modularity
   (`document/extractors/{pdf,docx}.py`, `video/{analyze,probe,
   extract,atoms}.py`). Folding would create monster files and
   lose the per-format / per-responsibility separation. Leave
   alone.
3. **`__main__.py` and `config.py`** decomposition (logged in
   `MEMORY.md → project-consolidation-pass`) — Independent of this
   inventory; the size issue isn't load-bearing-package status.
4. **`cli/` coverage** (60.8%) — 1,541 uncovered statements in CLI
   subcommands. Many `--help` and argparse paths; cheap to test.

What the consolidation pass should NOT do:

- Prune any subpackage on "looks aspirational" grounds. The data shows
  every subpackage is wired and tested.
- Merge any of the heavy hubs (`safety`, `providers`, `agent`, `tools`,
  `skills`) — their import surface is load-bearing.

---

## How to regenerate this report

```bash
python -c "
import re
from pathlib import Path
from collections import Counter, defaultdict
athena = Path('athena')
pkgs = sorted([p.name for p in athena.iterdir() if p.is_dir() and not p.name.startswith('_') and (p / '__init__.py').exists()])
import_counts = Counter()
import_callers = defaultdict(set)
for py in Path('athena').rglob('*.py'):
    text = py.read_text(encoding='utf-8', errors='replace')
    rel = py.relative_to('athena')
    caller_pkg = rel.parts[0] if len(rel.parts) > 1 else 'top-level'
    for m in re.finditer(r'from athena\.(\w+)', text):
        pkg = m.group(1)
        if pkg in pkgs and pkg != caller_pkg:
            import_counts[pkg] += 1
            import_callers[pkg].add(caller_pkg)
    for m in re.finditer(r'from \.\.([\w]+)', text):
        pkg = m.group(1)
        if pkg in pkgs and pkg != caller_pkg:
            import_counts[pkg] += 1
            import_callers[pkg].add(caller_pkg)
for pkg in pkgs:
    callers = sorted(import_callers[pkg])
    print(f'{pkg:<20} {import_counts[pkg]:>8}  {\", \".join(callers)}')
"
```

Combine with the coverage census numbers for the full table.
