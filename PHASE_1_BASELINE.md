# Phase 1 — Production Test Plan Baseline

Generated: 2026-05-23

Baseline measurements before adding any new tests. References
`PRODUCTION_TEST_PLAN.md` Phase 1 ("Measure what we actually have").

---

## Headline numbers

| Metric | Value |
|---|---|
| **Overall line coverage** | **76.9%** (23,121 / 29,414 statements) |
| Total source files (athena/) | 47 subpackages, ~300 modules |
| Total test files | 327 (`pytest --collect-only` count) |
| Currently-failing tests | **0** (3 stale, fixed during this audit) |
| Skip/xfail markers | 24 (all legitimate env/platform guards) |
| Broad-except sites | 421 across 130 files |

**Coverage target from plan:** 80% line / 70% branch. We are **3.1 points below the line target** overall, with the gap concentrated in a few user-facing subsystems.

---

## Line coverage by subpackage

Sorted by absolute number of uncovered lines (where the work actually is).

### 🔴 Critical (line coverage < 65%)

| Subpackage | Line % | Branch % | Covered / Stmts | Risk |
|---|---|---|---|---|
| `commands/` | 60.3% | 53.2% | 774 / 1,283 | Slash-command handlers — user-facing surface |
| `cli/` | 61.4% | 52.9% | 1,951 / 3,178 | All `athena <verb>` subcommand entry points |

These match the predictions in the plan (test-to-source file ratios were 0.18 and 0.27). **First targets for Phase 2.**

### 🟡 Worrying (line coverage 65-75%)

| Subpackage | Line % | Branch % | Covered / Stmts | Notes |
|---|---|---|---|---|
| `mcp/` | 68.0% | 60.0% | 926 / 1,362 | OAuth, HTTP/SSE transport, network surface |
| `audio/` | 70.3% | 65.4% | 204 / 290 | Backend optional, but coverage of the abstraction is light |
| `tools/` | 71.1% | 62.7% | 1,322 / 1,860 | 538 uncovered tool lines |
| `memory/` | 71.3% | **47.2%** | 263 / 369 | Branch coverage lowest in repo |
| `tui_gateway/` | 72.0% | **49.0%** | 684 / 950 | Wire format / handshake / heartbeats |
| `transform/` | 72.7% | 70.0% | 651 / 896 | Training loop |
| `lsp/` | 73.3% | 70.0% | 173 / 236 | Two-file subpackage; covered surface is fine but uncovered paths are LSP error handling |
| `ocr/` | 74.4% | 75.0% | 148 / 199 | Optional backend |
| `prompts/` | 74.6% | 61.4% | 100 / 134 | System prompt assembly |
| `document/` | 75.5% | 74.1% | 315 / 417 | Doc extractors |

### 🟢 Good (75-85%)

agent (78.4), `__root__` (76.8 — top-level files), gateway (80.5), browser (79.4), migration (78.8), recall (77.7), social (76.1), delegate (76.6), computer (81.3), acp (82.6), update (83.4), video (81.7), curator (85.9).

### 🟢 Excellent (≥ 85%)

vision (86.6), batch (86.4), webhooks (86.7), plugins (87.3), safety (**89.6**), audit (90.0), proxy (90.5), sessions (90.6), videogen (90.6), providers (**91.5**), skills (**91.9**), eval (93.1), cron (93.6), review (93.1), user_model (93.1), headless (92.4), tasks (95.3), verify (95.3), profiles (97.6), goal (97.1), sandbox (98.9), cache (98.1), steer (100), media (100).

---

## Failing tests

**0 currently failing** after this audit fixed:

| Test | Failure | Fix |
|---|---|---|
| `tests/agent/test_context_compressor.py::test_split_protects_head` | `TypeError: _split_head_middle_tail() takes 1 positional argument but 2 were given` | Test was calling `_split_head_middle_tail(msgs, cfg)` but prod refactored to keyword-only `head_indices=` and `tail_budget_tokens=`. Updated three call sites. |
| `tests/agent/test_context_compressor.py::test_split_protects_tail_by_token_budget` | same | same |
| `tests/agent/test_context_compressor.py::test_split_with_long_session_fixture` | same | same |

Suite-wide run: 0 fail, ~600+ pass, ~18 skipped (matches the 24 env-gated skip markers — several only trigger on specific platforms).

**Latent issue noticed (not a test failure):** the OpenTelemetry SDK emits `ValueError: I/O operation on closed file.` at process teardown. Cosmetic on local runs; would be noise in CI logs. **File as a separate issue;** likely fixed by shutting down the OTel exporter explicitly before the test framework closes stdout.

---

## Skip / xfail triage

All 24 skip sites are **legitimate platform/environment guards.** None hide bugs.

| Category | Count | Examples |
|---|---|---|
| POSIX-only tests | 7 | `tui_gateway/test_transport.py` (UDS sockets), `mcp/test_token_storage.py` (POSIX 0600 perms), `safety/test_path_security.py` (/etc/hostname) |
| Windows-only tests | 3 | `tui_gateway/test_transport.py` (TCP default), MSYS path quirks in safety + tools |
| ffmpeg-dependent | 7 | All in `tests/video/test_analyze.py` — gracefully skipped when ffmpeg absent |
| Optional dep gated | 2 | `transform/test_review_tui.py` (`importorskip("textual")`), `tui_gateway/test_bundle_packaging.py` (bundle-missing) |
| Capability-only providers | 2 | `providers/test_supports_parity.py` (skipping chat-backend tests for capability-only providers) |
| Runtime-conditional | 3 | Schema parity (TS file path check), subprocess-spawn smoke (Node availability), MSYS-only collision test |

**Action: none.** All skips have a `reason=` string and a `skipif` condition that's correct.

---

## Broad-except audit

**421 sites across 130 files.** Top offenders:

| File | Count | Verdict |
|---|---|---|
| `athena/agent/core.py` | 32 | **OK.** Spot-check of 30 shows ~85% are observability/init paths with explicit `noqa: BLE001` and logger calls. Pattern is "this code is non-critical and must never break a foreground turn" — defensible. **2 to investigate**: lines 769/779 (`except Exception: return None` — silent error→None) and 1731 (`except Exception: pass` — true silent swallow). |
| `athena/ui.py` | 13 | UI/render code; broad-except is correct here (never break the renderer). |
| `athena/plugins/bundled/observability/plugin.py` | 11 | Runs on every turn. **Worth a line-level review** — observability bugs should fail loudly, not silently. |
| `athena/gateway/base.py` | 10 | Adapter base; network surface. |
| `athena/gateway/platforms/discord.py` | 10 | Discord gateway. |
| `athena/proxy/server.py` | 10 | HTTP proxy server. |
| `athena/gateway/platforms/*` (telegram, slack, matrix, imessage, email) | 6–8 each | Messaging adapters; defensible for inbound webhook handlers but should be audited for outbound write paths. |
| `athena/lsp/client.py` | 8 | LSP client; LSP servers crash often, broad-except is correct. |

**Verdict:** The pattern is mostly defensible. The real risk lives in **network adapters and observability code** — not in the agent core. Prioritized review list:

1. `plugins/bundled/observability/plugin.py` (silent obs bugs are insidious)
2. `gateway/platforms/discord.py`, `telegram.py`, `slack.py` (inbound message handling — security surface)
3. `proxy/server.py` (HTTP boundary)
4. `agent/core.py:769`, `:779`, `:1731` (the three "silent return None / pass" sites)
5. Everything else can stay; replacing 400 broad-excepts is not worth the regression risk.

---

## Coverage gate (recommendation)

Plan calls for failing CI below 80% line / 70% branch. Current numbers say:

- **Line: 76.9%** — set initial gate at **75%** to avoid same-day regression; tighten to 80% after Phase 2 fills `commands/` + `cli/` (biggest gaps).
- **Branch: not aggregated** in current run config, but per-subpackage shows several below 60% (memory 47%, tui_gateway 49%, cli 53%, commands 53%, recall 60%). Set initial branch gate at **55%** with intent to ratchet up.

Wire this into `.github/workflows/coverage.yml` by adding `--cov-fail-under=75` and a `--cov-branch --cov-fail-under-branch=55` once we're sure the workflow uses a version of coverage that supports per-branch threshold (older `pytest-cov` doesn't — use `coverage report --fail-under` post-run as fallback).

---

## Phase 1 deliverables — done

- ✅ Coverage baseline number per subpackage (`coverage_phase1.json` + table above)
- ✅ Skip-marker triage (all 24 categorized; no action needed)
- ✅ Broad-except inventory (top files identified; prioritized review list of 5 files instead of 421)
- ✅ Failing tests fixed (3 stale callsites in `test_context_compressor.py`)

## What Phase 2 should target

The plan calls for filling underweight subpackages. Now-real priorities (sorted by uncovered-line count):

1. `cli/` — **1,227 uncovered lines** at 61.4%. One test per `athena <verb>` covering arg parsing, missing-arg error, and success exit code. Stub network with respx.
2. `tools/` — **538 uncovered lines** at 71.1%. Per-tool happy-path + one error path.
3. `commands/` — **509 uncovered lines** at 60.3%. One test per slash command.
4. `agent/` — **315 uncovered lines** at 78.4%. Despite the high % the absolute count is significant; target the adversarial paths from Phase 3a of the plan.
5. `memory/` — branch coverage is **47%**. Add property tests over the markdown↔sqlite reconcile path.
6. `tui_gateway/` — branch coverage **49%**. The wire format / handshake / heartbeat error paths are the gap.
