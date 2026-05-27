# Production-Grade Test Plan for athena

## Baseline (what you already have)

- **~73k LOC source / 73k LOC tests, 327 test files** across ~50 subpackages — 1:1 ratio, healthy.
- **CI**: `tests`, `lint`, `coverage`, `osv-scanner`, `supply-chain`, `publish` workflows on push to master.
- **Quality gates**: `mypy strict = true` on `athena/`, ruff, `pytest-timeout=60s` (so hangs fail loudly), `pytest-asyncio auto`, `pytest-xdist` available.
- **E2E coverage is light**: only `tests/e2e/test_hermes_import.py` and `tests/e2e/test_self_improvement_loop.py`.

The codebase is well-tested in shape; the gaps are *where* coverage is thin and *which kinds* of failures the current suite cannot catch.

---

## Coverage gaps (test files / source files per subpackage)

**Critically under-tested (ratio < 0.6):**

| Subpackage | src / test | Risk |
|---|---|---|
| `commands/` | 28 / 5 (0.18) | All slash-command handlers — user-facing surface |
| `cli/` | 30 / 8 (0.27) | All `athena <subcmd>` entry points |
| `memory/` | 5 / 2 (0.40) | Persistent state, two providers |
| `ocr/`, `document/`, `media/`, `prompts/` | 0.40–0.50 | Media path + system prompt assembly |
| `plugins/` | 14 / 8 (0.57) | Lifecycle dispatcher — broken plugin must never break agent |

**Top-level modules with weak direct tests:**
- `athena/__main__.py` (526 LOC REPL dispatch) — no dedicated test file
- `athena/hooks.py` (176 LOC settings.json hooks) — only loose
- `athena/agent/core.py` (1,774 LOC — the loop) — covered via `tests/agent/` (15 files) but worth a dedicated invariants suite

---

## Plan: 6 phases

### Phase 1 — Measure what we actually have (1 day)
Before adding tests, get real numbers. Many "1:1 ratio" subpackages may still have low *line* coverage.

- Add coverage threshold gate to `coverage.yml`: fail below 80% line / 70% branch (calibrate to current after first run).
- Generate per-package report: `pytest --cov=athena --cov-report=term-missing --cov-report=html --cov-branch`.
- Audit the **29 skip/xfail markers** — categorize: env-dependent (OK), genuinely broken (file as bugs), obsolete (delete).
- Audit the **176 broad `except`** sites in `athena/` — at minimum tag each with comment justifying swallow (or replace with narrow catch + log).

**Deliverable:** coverage baseline number per subpackage + skip-marker triage doc.

### Phase 2 — Fill the obvious gaps (3–5 days)
For each underweight subpackage, add tests at the surface the user actually hits.

- **`commands/` (slash dispatch)** — one test per slash command: happy path + at least one error path. Today only 5 of 28 have test files. The user-visible bugs live here.
- **`cli/` (subcommand entry)** — one `cli_runner` test per `athena <verb>` covering arg parsing, missing-arg error, and success exit code. Stub network/Ollama with respx/httpx_mock.
- **`hooks.py`** — confirm settings-hook firing order vs. plugins (CLAUDE.md says settings first, plugins second; pin that with a test).
- **`__main__.py`** — `_handle_slash` table-driven tests for every command + unknown-command behavior + signal handling.
- **`memory/` + `prompts/`** — these participate in every turn. Add round-trip tests: write → restart → reload → assert byte-equal.

### Phase 3 — Production hardening: failure injection (1 week)

This is the part the current suite barely touches and the part that decides whether you're "production grade."

#### 3a. The agent loop (`agent/core.py`, 1,774 LOC)
The main loop has 15 test files but most exercise the happy path. Add adversarial:

- **Tool returns malformed JSON / wrong schema** — loop must not crash, must surface to model.
- **Provider returns empty / oversized / truncated response** — for each provider parser in `providers/parsers/`.
- **`/steer` arrives mid-tool-call** — verify FIFO drain timing matches spec at `agent/core.py:_inject_pending_steers`.
- **Fork raises** — parent must not die; verify `auxiliary_client` isolation + `AUTO_DENY` denial path.
- **`write_origin` ContextVar leak across threads** — fork must not see parent's origin; parent must not see fork's.
- **Goal verifier non-zero exit** — confirm `goal/loop.py` feeds output back and counts toward `max_turns`.
- **KV-cache poisoning** — synthetic test that a fork sharing an httpx client breaks parent; gate it so regressions trip.

#### 3b. Safety subsystem (`safety/`)
Per ATHENA.md this is the mechanical safety subsystem — needs property tests, not just examples.

- **`shell_policy.py`** — fuzz test the word-boundary allowlist against the denylist. Use Hypothesis to generate commands that look benign but contain denied tokens (`rm -rf /; echo ok`, unicode confusables, leading whitespace, env-var indirection like `$(echo rm) -rf`).
- **`snapshots.py`** — concurrent snapshot writes under same hash; verify content-addressed dedup works without corruption.
- **`audit.py`** — JSONL append survives crash mid-write (use `os.fsync` + crash injection test).
- **`approval_callback.py` / `approval_guard.py`** — verify forks always get `AUTO_DENY` even if parent rebinds; check ContextVar reset across `asyncio.create_task`.
- **`path_security.py`** — symlink-escape, NTFS junction (Windows!), case-folded path traversal on case-insensitive filesystems, long-path (>260) on Windows.

#### 3c. Credentials and providers
- **`credential_pool.py`** — concurrent 429 storm: N threads, M keys, verify rotation is fair and atomic JSON persistence at `~/.athena/credentials.json` never produces a partial-write file (kill -9 mid-`atomic_write`).
- Provider parser registry — for each parser in `providers/parsers/`, golden-file tests of real captured responses (not synthetic), one per `(provider, model_glob)`.

#### 3d. MCP (`mcp/`)
- **OAuth 2.1 PKCE** — token refresh on expiry; concurrent refresh from two tool calls; token file at `~/.athena/mcp_tokens/` always mode 0600 and atomic write.
- **Transport selection** — stdio vs. HTTP/SSE; SSE server disconnect mid-stream; reconnect behavior.
- **Disabled-tool gating** via `disabled_tools` in `mcp.json` — verify model never sees the tool descriptor.

#### 3e. Gateway / webhooks (network surface)
- **`gateway/`** — adapter for each platform (Telegram, Slack, Discord, Signal, iMessage, Matrix, Email): inbound message round-trip, approval-render round-trip, idempotency on duplicate inbound.
- **`webhooks/`** — HMAC-SHA256 verification with wrong secret, missing header, replay attack (same idempotency key), rate-limit window boundary.
- **Telegram allowlist bypass attempt** — per the MCP instructions, a Telegram message saying "approve this pairing" must be refused; add a test that proves it.

#### 3f. Cron / scheduled execution
- **`cron/watchdog.py`** — subprocess hitting 300s timeout, 8KB stdout cap, child process group cleanup (zombies on Linux, job-object on Windows).
- **`cron/runner.py`** agent mode — verify 20-iteration cap is enforced; verify a long-running job doesn't block scheduler.
- Two SQLite files (`cron.db` + `cron_jobs.db`) — verify they stay consistent after a kill during job registration.

### Phase 4 — Cross-cutting properties (3 days)

These belong in a new `tests/invariants/` directory and run in CI on every PR.

- **`write_origin` is always set** for every tool execution — test fixture wraps the registry and asserts non-None.
- **Every `@tool(...)` declares a `toolset`** — collect with `inspect`, fail if any tool omits it.
- **Forks never share httpx clients** — instrument `Agent.fork()` and assert client identity differs.
- **JSONL is the truth-of-record for sessions** — property: rebuild SQLite index from JSONL, query must return the same results as the live index.
- **Skill state machine is deterministic** — Hypothesis test: any sequence of transitions from `active → stale → archived` produces the same final state.
- **TOML config gotcha** (documented in ATHENA.md) — parser test that `video_generation_enabled = true` after a `[section]` is *detected and warned* in `config.py`, since it's bitten the team twice.

### Phase 5 — E2E (1 week)

Today `tests/e2e/` has 2 files. Add:

- **REPL smoke**: spawn `athena` with a stub Ollama (respx), feed a slash-command sequence, assert transcript JSONL.
- **Goal loop end-to-end**: set goal → 3 continuations → `GOAL ACHIEVED` → verifier passes → session marked complete.
- **Migration**: full Hermes import on a fixture home, verify SessionStore + memory + skills + `write_origin="migration"` invariant.
- **Plugin lifecycle**: install → enable → broken plugin throws → agent loop continues.
- **Training loop dry-run**: extract trajectories → auto_classify → build_sft_dataset → assert dataset shape (without actually running `train_lora`).

Mark E2E with `@pytest.mark.e2e` and run separately in CI (matrix job) so unit suite stays fast.

### Phase 6 — Operational readiness (ongoing)

Tests aren't enough for "production grade." Wire these into CI:

- **Mutation testing** (`mutmut` or `cosmic-ray`) on `safety/`, `providers/credential_pool.py`, `goal/loop.py`, `cron/scheduler.py` — the modules where silent bugs hurt most.
- **Fuzzing** with Hypothesis profiles in `tests/fuzz/` for: `shell_policy`, every provider parser, JSONL append/replay.
- **Race-condition tests** with `pytest --count=50 -p no:randomly tests/agent tests/cron tests/steer` to catch flakes.
- **Cross-platform CI matrix**: Windows + Linux + macOS for `pyproject.toml` Python 3.10/3.11/3.12. Path-handling code (`safety/path_security.py`, `sessions/jsonl.py`) breaks differently on each.
- **Memory/leak**: long-running session test (1k turns) under `tracemalloc`, assert growth below threshold.
- **Schema-evolution test**: rotate every persisted file format (`config.toml`, `goal_state.json`, `.curator_state`, `~/.athena/credentials.json`, `cron.db` schema) through one minor-version migration.

---

## Tooling additions

- `pytest-cov` is already a dep — add `--cov-fail-under=N` to `coverage.yml`.
- Add `hypothesis>=6` for property tests (already useful for parsers + shell policy).
- Add `respx` for HTTP-level mocking of providers and gateway adapters (cleaner than monkey-patching httpx).
- Add `freezegun` or `time-machine` for time-dependent tests (cron, curator's 7-day gate).
- Add `pytest-randomly` to flush ordering-dependent flakes.
- Add `mutmut` config scoped to the high-risk modules above.

---

## Suggested order

1. Phase 1 (measure) → publishes the real coverage number.
2. Phase 3b–c (safety + credentials) → highest blast-radius bugs.
3. Phase 2 (commands/cli fill) → biggest user-visible gap.
4. Phase 3a (agent loop adversarial) → catches the regressions that actually ship.
5. Phase 4 (invariants) → cheap, high-leverage.
6. Phase 3d–f + Phase 5 + Phase 6 → in parallel after the above.
