# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `athena proxy` subcommand: local OpenAI-compatible HTTP endpoint with OpenAI ↔ Anthropic translation; provider routing by config or `X-Athena-Provider` header; transparent prompt caching, retry, and rate-limit tracking via existing provider machinery; FastAPI/uvicorn ship under the new `[proxy]` optional-extra so headless installs stay slim. `/v1/models`, `/v1/chat/completions` (streaming + non-streaming), `/v1/embeddings` (501 stub). Smoke runbooks for Aider and alternate clients in `docs/proof/`. 54 tests across translator (25), router (10), proxy logger (7), and server (12) (T3-01).
- Proxy translator (`athena/proxy/translator.py`): pure functions for OpenAI → Anthropic request shape (system hoist, tool unwrap, role=tool fold into tool_result blocks, tool_choice mapping) and Anthropic stream events → OpenAI SSE chunks (role chunk, text deltas, tool_calls fragments, finish_reason). Sync — adapts at FastAPI boundary (T3-01).
- Proxy router (`athena/proxy/router.py`): `route_request()` resolves a provider in three steps — `X-Athena-Provider` header (case-insensitive) → model-name match against `KNOWN_MODELS_PER_PROVIDER` → fallback to `proxy_default_provider`. Raises `RouteError` with available-provider list when the default isn't reachable (T3-01).
- Proxy traffic log (`athena/proxy/logging.py`): one JSONL line per completed request in `~/.athena/proxy.jsonl` (request_id, ts, client_ua, model_requested, provider_used, latency_ms, tokens_in/out, cache_read_tokens, request/response summary). Opt-in full request/response bodies under `~/.athena/proxy_bodies/<id>.json` behind `proxy_log_bodies = true` (T3-01).
- `athena/proxy/server.py` exports `make_app(cfg, pool, provider_factory)`, `stream_chunks_to_openai_sse`, `collect_chunks_to_openai_response`. The server bridges athena's sync `Iterator[StreamChunk]` providers to async SSE via FastAPI's threadpool — keeps caching/retry/rate-limit on the path; the dedicated Anthropic-format translator is reserved for a future `--no-translate` deep-integration mode (T3-01).
- `athena proxy` CLI flags: `--host`, `--port`, `--bind-public`, `--provider`, `--log-bodies`, `--no-translate`. Default binds 127.0.0.1:11434 (Ollama's port — slots in cleanly for tools already configured for Ollama). `--bind-public` is the only way to bind 0.0.0.0 and prints a warning (T3-01).
- Eight proxy config fields under `Config`: `proxy_default_provider` (default `"anthropic"`), `proxy_bind_host`, `proxy_bind_port`, `proxy_require_auth`, `proxy_log_path`, `proxy_log_bodies`, `proxy_bodies_dir`, `proxy_no_translate` (T3-01).
- `docs/reference/proxy.md` reference; `docs/proof/proxy-aider-runbook.md` + `docs/proof/proxy-clients-runbook.md` operator runbooks for the manual integration tests (T3-01).
- `clarify` tool: multiple-choice question for ambiguous requests. Foreground path is a stdin prompt with numeric / case-insensitive label / unique-prefix resolution. Background forks (curator, auxiliary, background review) AUTO_DENY via the `in_fork_context` ContextVar so the fork can't block on stdin it doesn't own. Pluggable `GatewayClarifyHook` for platform-native UIs in Tier 4 (Telegram inline keyboards, Discord button rows, Slack block kit) (T2-08).
- `clarify_default_timeout_seconds` (default 300) and `clarify_allow_freeform` (default False) config options (T2-08).
- `docs/reference/clarify-tool.md` documents the three resolution paths, input parsing priority, timeout behaviour, and the gateway-hook contract (T2-08).
- `patch_apply` tool. Accepts a unified-diff (the output of `diff -u`) and applies every hunk across every file atomically. Per-file backup + restore on partial failure means either the whole patch lands or no file is modified. `path_security.validate_path(intent="write")` runs on every target before any write. Useful for multi-callsite renames, multi-line refactors, and any edit that would otherwise need more than two `Edit` calls (T2-07).
- `patch_parser` module: pure `parse_patch(text)` → structured `Patch` and `apply_patch_to_text(original, file_patch)` → new content. Tolerates leading commit-message garbage; handles multi-file + multi-hunk diffs; processes hunks in reverse `old_start` order so earlier line numbers stay valid. Standalone of `patch_apply` so other tools can reuse the parsing (T2-07).
- `fuzzy_match` module: `find_fuzzy_matches(haystack, needle, *, threshold=0.95)` returns ALL near-matches above threshold (verbatim short-circuit returns score=1.0). Caller decides what to do with `len(matches) != 1` — the matcher never picks one of N. Backend: rapidfuzz if installed, difflib.SequenceMatcher otherwise (no hard dependency) (T2-07).
- `Edit` (str_replace) gains opt-in `fuzzy: bool = False` and `fuzzy_threshold: float = 0.95` parameters. When verbatim count is zero AND `fuzzy=True`, falls back to `find_fuzzy_matches`. Exactly-one match -> apply at the matched slice, return line carries `(fuzzy: score=..., matched N chars)`. Zero or multiple matches -> ERROR with a recovery hint. Default behaviour unchanged (T2-07).
- `docs/reference/patch-and-fuzzy-edit.md` documents the patch_apply atomicity contract, the fuzzy fallback's safety properties, and when to use each (T2-07).
- Out-of-band tool result storage. Tool outputs exceeding `tool_result_threshold_bytes` (default 1MB) are persisted as content-addressed blobs (SHA-256 first 16 hex chars) under `~/.athena/tool_results/` and replaced in conversation history with a short `[tool_result:<hash> — <size> output stored. Use read_tool_result to access.]` handle. `PostToolUse` hooks + plugins still see the raw result; only the version that lands in `agent.messages` / session JSONL is the handle (T2-06).
- `read_tool_result` tool. Accepts the full handle, the bare 16-hex hash, or the prefixed `tool_result:<hash>` form. Pagination via `offset` + `max_bytes` lets the agent stream large blobs without re-inlining (T2-06).
- `athena cleanup-blobs` CLI subcommand. Walks every `profiles/<name>/sessions/*.jsonl`, collects every handle/bare-hash reference, deletes unreferenced blobs older than `--older-than` (default 30) days. `--dry-run` counts but doesn't delete. Recent blobs always kept regardless of reference state (T2-06).
- Config: `tool_result_threshold_bytes` (default 1_000_000) and `tool_result_storage_path` (default `~/.athena/tool_results`) (T2-06).
- `docs/reference/tool-result-storage.md` documents how the storage works, the cleanup contract, configuration, and limitations (T2-06).
- Tool-call argument sanitizer. `athena.providers.schema_sanitizer.sanitize_tool_call_args(raw, *, tool_name)` recovers malformed JSON in tool-call arguments via a 5-pass pipeline (smart quotes → ASCII; single-quoted → double-quoted only when safe; trailing commas removed; unquoted top-level keys quoted; optional `demjson3` fallback if installed). Pure function, never modifies tool names, returns `None` rather than speculate when recovery requires semantic guesses (T2-05).
- `Agent._handle_tool_call` routes string-shaped tool arguments through the sanitizer before `json.loads`, gated by `cfg.tool_call_sanitize` (default True). When a fix applies, the REPL surfaces `sanitised tool-call args for <name>: <fixes>`; unrecoverable payloads fall through to the existing fallback (empty args dict) with a WARNING log line carrying the truncated payload (T2-05).
- `tool_call_sanitize` config option (T2-05).
- `docs/reference/schema-sanitizer.md` documents the pass order, contract guards, configuration, and known limitations (T2-05).
- Automatic context compression. `athena.agent.context_compressor` summarises the middle of a long conversation while preserving head (system prompt) and tail (most recent turns by token budget) verbatim. Triggered proactively when total tokens > `context_compress_watermark` × `context_window` (default 0.75) inside the agent's tool-round loop, or manually via `/compact` (T2-04).
- Structured summary template: Resolved questions / Pending questions / Decisions made / Tool outputs of lasting value / Remaining work (NOT "Next steps" — hermes-learned model-behaviour gotcha). Synthetic summary lands as a `role="system"` message starting with the `[Compressed summary of turns N–M, ...]` marker (T2-04).
- Iterative compression: earlier summaries are detected via the marker and carried forward as input to later compactions, so information survives multiple compressions at graceful fidelity decay (T2-04).
- Prompt-injection-safe summariser preamble: tool outputs containing injected directives are framed as SOURCE MATERIAL, not as instructions the summariser should follow (T2-04).
- Cheap tool-output pre-pass: `tool`-role messages in the to-be-compressed middle are pruned to `tool_output_prune_tokens` (default 200) before being fed to the summariser (T2-04).
- `/compact` slash command upgraded to use the new compressor (replaces the prior inline summary-then-replace-all-after-system implementation) (T2-04).
- Config options: `context_compress_watermark`, `tail_protection_ratio`, `tool_output_prune_tokens`, `summary_budget_ratio`, `summary_budget_cap_tokens` (T2-04).
- `docs/reference/context-compression.md` documents the watermark, head/tail layout, summary format, iterative carry-forward, injection-defence, persistence, and configuration (T2-04).
- Error classifier and retry/backoff. `athena.providers.error_classifier.classify(exc, ...)` returns a 5-action `Classification` (`retry` / `rotate_credential` / `fallback_provider` (reserved) / `compress_context` / `abort`) plus an `ErrorClass` for logging (`network`, `server_5xx`, `rate_limit`, `timeout`, `client_4xx`, `context_length`, `stream`, `parse`, `unknown`). Pure function, no I/O (T2-03).
- `athena.providers.retry_utils.with_retry(operation, ...)` executes recovery: exponential backoff + jitter capped at `max_backoff_seconds`, `Retry-After` header respected (also capped), `on_rotate_credential` / `on_compress_context` callbacks, `RetryBudgetExceeded` on cap (T2-03).
- Every provider (Anthropic, OpenAI, OpenRouter, Nous, OpenAI-compat, Ollama) wraps its `POST` + `raise-for-status` + rate-limit-header-capture in `with_retry`. The streaming body stays outside the retry boundary (yielded chunks can't be replayed). `ExitStack.pop_all` keeps the open response alive past the retry boundary (T2-03).
- `CredentialPool.rotate_to_next(provider_name) -> Credential | None` — the pool's contribution to the `on_rotate_credential` callback (T2-03).
- `max_retries_per_turn` (default 5) and `max_backoff_seconds` (default 30.0) config options (T2-03).
- `/status` "retries this session" section displays `<provider>: N retries, M aborts` per provider (T2-03).
- `docs/reference/error-handling.md` documents the taxonomy, priority order, configuration, interrupt propagation, and implementation seam (T2-03).
- Rate-limit header tracking. `athena.providers.rate_limit_tracker.RateLimitTracker` parses the standard 12-header generic schema (Nous, OpenRouter, OpenAI) and Anthropic's `anthropic-ratelimit-*` schema (ISO-8601 resets normalised to Unix seconds). Per-(provider, credential) trackers stored on each provider; `should_throttle()` decides preemptively, `throttle_seconds()` caps the sleep at 60 s (T2-02).
- `rate_limit_throttle_threshold` config option (default 0.95). Below the threshold a provider sleeps before the next request rather than waiting to trip 429 (T2-02).
- `/status` "rate limits" section surfaces `<credential_id>: <tracker.format()>` per provider when state is available (T2-02).
- `CredentialPool.get_credential_rate_state()` returns per-(provider, credential) cooldown / 429 / fail-count view, keyed by the same `...<last-4>` suffix the providers' tracker dicts use (T2-02).
- `docs/reference/rate-limits.md` documents the schemas, configuration, provider coverage, and persistence semantics (T2-02).
- Anthropic prompt caching: 4-breakpoint `system_and_3` layout
  (last system message + last 3 non-system messages), 5m default
  TTL / 1h opt-in via `prompt_cache_ttl = "1h"`, ~60-75% input-token
  cost reduction on multi-turn sessions against Anthropic-direct,
  OpenRouter, or Nous Portal. Pure-function module
  `athena.agent.prompt_caching` with `apply_cache_markers` and
  `strip_cache_markers` (T2-01).
- `cache_strategy` and `prompt_cache_ttl` config options. Defaults:
  `"system_and_3"` and `"5m"`. Disable via `cache_strategy = "none"`
  (T2-01).
- `Stats.cache_read_tokens` and `Stats.cache_creation_tokens`
  populated from each provider call's usage chunk; surfaced in
  `/status` under the `tokens` block when non-zero (T2-01).
- `docs/reference/prompt-caching.md` documents the layout, config,
  provider coverage, persistence, and limitations (T2-01).

### TODO before tagging v0.2.0

(empty — all Tier 1 follow-ups closed; v0.2.0 is gated only on the
user pushing the `v0.2.0` tag to trigger the publish workflow.)

### Changed
- Slash-command dispatcher refactored into a uniform table. `_handle_slash`
  in `athena/__main__.py` now routes 12 inline commands (`/help`,
  `/model`, `/models`, `/tools`, `/mcp`, `/clear`, `/cost`, `/status`,
  `/save`, `/dump`, `/hooks`, `/cwd`) through `_INLINE_SLASH_HANDLERS`
  rather than an elif chain. Module-based commands (`/compact`,
  `/goal`, `/init`, `/loop`, `/memory`, `/plan`, `/resume`, `/review`,
  `/steer`) still flow through `commands.get_command` unchanged. A
  future move of the inline handlers into `athena/commands/*` is now
  a pure rename per row.

## [0.2.0] - 2026-05-19

### Added

- `athena --version` flag reading `athena.__version__` (single source of truth via `scripts/verify_version.py` CI gate) (T1-02)
- `pytest-cov>=4.1` + `pytest-timeout>=2.3` in `[project.optional-dependencies].dev`; pytest configured with `timeout=60` so hung tests fail loudly instead of wedging CI runners (T1-01)
- `CHANGELOG.md` reorganized to [Keep-a-Changelog](https://keepachangelog.com/en/1.1.0/) format with `## [Unreleased]` + `## [0.2.0]` versioned sections; `RELEASE_v0.2.0.md` at repo root summarizes the release for the GitHub Releases UI; `docs/internal/release-process.md` is the operator checklist (T1-03)
- Agent core unit test suite under `tests/agent/` covering `core.run_turn`, `core.run_until_done`, `fork.Agent.fork()`, and `auxiliary_client` — 22 tests bringing `athena.agent` coverage to 62% (T1-04)
- _(planned; lands as T1-07 ships)_ Path security module sandboxing file operations to the workspace; outside-workspace writes require explicit approval (T1-07)
- _(planned; lands as T1-08 ships)_ SSRF defense on the web tool: blocks RFC1918, link-local, loopback, and cloud-metadata IPs by default (T1-08)
- **PyPI publishing via trusted publishing** (T1-02) — `.github/workflows/publish.yml` fires on every `v*` git tag push. Builds sdist + wheel once, then routes the artifacts to TestPyPI (for `v*-rc*` / `v*-beta*` / `v*-alpha*` tags via PEP 440 pre-release detection) or real PyPI (for everything else). Uses OIDC trusted publishing — no `PYPI_API_TOKEN` secret in repo settings. Both publish jobs target named GitHub environments (`testpypi` / `pypi`) so a maintainer can optionally pin a manual-approval gate per release. `workflow_dispatch` inputs let you re-run a failed publish without burning a fresh tag.
- **Project metadata for PyPI** — `pyproject.toml` now carries `readme`, `license` ("MIT"), `license-files`, `authors`, `keywords`, `classifiers`, and `[project.urls]` (Homepage, Repository, Issues, Changelog). Distribution name is `athena-coder` because both `athena` and `athena-agent` are taken on PyPI by unrelated active projects; the import name and CLI shims (`athena`, `ocode`) are unchanged.
- **LICENSE file** — MIT, 2026.
- **`docs/release.md`** — operator runbook covering the one-time PyPI / TestPyPI trusted-publisher registration, the standard release flow (`git tag v0.2.1 && git push origin v0.2.1`), pre-release staging via `*rc*` tags, manual re-dispatch on flaky publish, and yank/rollback procedure.

- **GitHub Actions CI** (T1-01) — five workflows running on every push to `master` and every PR: `tests.yml` (pytest matrix on Python 3.10/3.11/3.12/3.13), `lint.yml` (ruff check + ruff format --check, with mypy strict landing as advisory until the T1-04 cleanup), `coverage.yml` (pytest --cov; gates the build at 60%, current floor is 75%), `osv-scanner.yml` (google/osv-scanner-action reusable workflow on push + weekly Monday 08:00 UTC), `supply-chain.yml` (pip-audit, advisory-only for now). Each workflow has a `concurrency` group that cancels in-progress runs on new pushes to the same PR. Test workflow uses `fail-fast: false` so one Python version's failure doesn't hide others. No secrets referenced.
- **Dependabot** (`.github/dependabot.yml`) — weekly pip + github-actions bumps. Dev-tool updates (ruff, mypy, pytest*) grouped into one PR so unrelated bumps don't flood the queue. Limit 5 open PRs at a time.
- **README CI badges** — five SVG status badges immediately under the H1 linking to each workflow page on Actions.
- `pytest-cov>=4.1` in `[project.optional-dependencies].dev`.

- **Mechanical safety subsystem (Phase 17)** — content-addressed snapshot store, mutation audit log, ContextVar-scoped approval guard, word-boundary shell allowlist with denylist. Every agent-driven mutation (skill_manage, memory writes, background-fork tool calls) now wraps in a snapshot+audit context so any change is byte-exact rollback-able and forensically attributable. Snapshot tarballs are stored under `~/.athena/snapshots/YYYY/MM/DD/<ts>-<sha[:12]>-<origin>.tar.gz` with a sidecar JSON carrying `snapshot_id`, `write_origin`, `session_id`, `tool_name`, `tool_call_id`, `paths`, `created_at`, `athena_version`, `parent_session_id`, and pin state. Identical pre-states under the same write_origin at the same second collapse to one tarball (content addressing).
- **Append-only mutation audit log** at `~/.athena/audit/mutations-YYYY-MM.jsonl` — one compact JSON line per mutation with `timestamp`, `write_origin`, `session_id`, `parent_session_id`, `tool_name`, `tool_call_id`, `path`, `snapshot_id`, `sha_before`, `sha_after`, `byte_delta`. `threading.Lock` serialises appends; monthly rollover; existing files preserved across appends. (Phase 17.4)
- **ContextVar-scoped approval guard** (`athena.safety.approval_guard`) — foreground prompts cache approvals per-resource for the lifetime of the ContextVar scope. `Agent.fork()` now installs `scope_fresh_approvals()` so a background fork starts with an empty grant cache and any `request_approval` call from background origin raises `ApprovalDeniedInBackground` (unless the resource is explicitly marked `auto_approve_in_background=True`). The cache is never consulted from background even if a foreground grant for the same resource exists. (Phase 17.2)
- **Word-boundary shell policy** (`athena.safety.shell_policy`) replaces the previous substring allowlist. Allowlist entries compile to `^<escaped-entry>\b` and match the binary token after stripping environment-variable assignments — so `git` no longer matches `gitlab-cli` or `.git/hooks/...`. Always-on denylist covers `rm -rf` of system roots, `dd of=/dev/...`, `mkfs.*`, fork bomb, `chmod 777 /`, `sudo rm -rf`, `curl | sh`, `wget | sh`, and block-device redirects. Extendable via `cfg.bash_extra_denylist`. The Bash tool calls `evaluate_denylist_only()` before execution and returns a `BLOCKED by shell policy: <reason>` tool error on match. (Phase 17.3)
- **Rollback CLI** — `athena snapshot {list, show, pin, unpin, prune}` for store inspection; `athena skill {diff, rollback} <name>` and `athena memory {diff, rollback} <name>` for restoring a single resource. Rollbacks are themselves audited (the post-restore record carries `tool_name="skill_rollback"` / `"memory_rollback"`, sha_before/sha_after inverting the original change). `--to <snapshot_id>` selects a specific snapshot; `-y` skips the interactive confirm. (Phase 17.6)
- **Per-profile snapshot/audit singletons** (`athena.safety.context`) — `get_snapshot_store(profile_dir)` and `get_audit_log(profile_dir)` lazily construct one store per profile root, keyed by resolved path so two concurrent profiles in the same process see their own directories. Re-resolves home each call so tests that monkeypatch `Path.home()` get tmp-scoped stores. (Phase 17.5)
- **CI grep guard** at `tests/safety/test_no_raw_writes.py` — walks `athena/` and fails the build if any module that isn't on the snapshot+audit allowlist calls `Path.write_text`, `Path.write_bytes`, `open(..., "w"|"a")`, `shutil.copy*`, or `shutil.rmtree`. The allowlist is frozen as of Phase 17.5; new write sites must route through `athena.safety.mutation.snapshot_and_record` or get an explicit one-line justification in the allowlist. (Phase 17.5)
- `cfg.bash_extra_denylist: list[str]` config field for appending regex patterns to the default shell denylist. (Phase 17.3)
- `athena.safety.mutation.snapshot_and_record(paths, *, tool_name, ...)` — combined context manager that takes the pre-state snapshot, captures `sha_before`/byte size per path, yields a `MutationContext`, and lets the caller emit the matching `MutationRecord` via `ctx.record(path)` once the mutation is complete. Used at every skill/memory mutation site. (Phase 17.5)

- **Observability plugin (bundled, opt-in)** — OpenTelemetry tracing + metrics + JSON structured logging under `athena/plugins/bundled/observability/`. Activate with `athena plugins enable observability`. Heavy OTel deps live behind `pip install -e ".[observability]"` so headless installs stay light. Spans: `athena.session` brackets every session; `athena.tool_call.<name>` per tool dispatch with arguments redacted; latency + count metrics tagged by `tool_name`. When `[plugins.observability].otlp_endpoint` is set, exports via OTLP/HTTP instead of the default stderr console exporter. Plugin loads and no-ops cleanly when the optional deps aren't installed. (Phase 16)
- **PII redaction** for span attributes — pattern table for OpenAI / Anthropic / Google / GitHub (classic + fine-grained `ghu`/`ghs`/`ghr`/`gho`) / Bearer / Slack tokens; constant-time replacement with `<redacted>`; length truncation at 200 chars with `…` suffix; defensive handling of non-dict / None inputs. (Phase 16)
- **`/status` slash command + `athena status` CLI** — read-only view of live counters (per-tool histogram, fork / review / curator counts, prompt/completion tokens, elapsed). Snapshot is atomically written to `<profile>/.status.json` on every turn end; the CLI reads it from any terminal and is profile-aware (`--profile` flag honored). The renderer (`render_status`) is shared between the two surfaces so they stay byte-identical. (Phase 16)
- **Benchmark harness** at `scripts/bench/` — `runner.py` discovers any module exporting `run() -> dict`, runs them, writes JSON results, optionally compares against a baseline and flags regressions over a configurable threshold (default 10%). Ships with `tool_call_latency` (Read tool dispatch) and `skill_discovery` (100-skill catalog walk) reproducible benches. Initial baseline committed at `tests/fixtures/benchmarks/baselines/main.json`. (Phase 16)
- `[observability]` optional extras group (`opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `python-json-logger`). (Phase 16)
- `Stats.tool_call_counts`, `Stats.fork_count`, `Stats.review_fired_count`, `Stats.curator_run_count`, `Stats.record_tool_call`, `Stats.to_snapshot`. `Agent.write_status_snapshot()` atomic writer fired at every `_fire_stop`. (Phase 16)

- **Webhook HTTP listener** — `aiohttp`-backed at `http://<host>:<port>/webhook/<id>` hosted inside the gateway daemon when `[gateway.webhooks].enabled = true`. Per-request flow: subscription lookup (404 on miss/disabled) → auth (HMAC-SHA256 or Bearer, 401 on fail; `auth_type="none"` for trusted networks) → idempotency cache (200 no-op on duplicate `X-Webhook-Idempotency-Key` within 10 min TTL) → per-webhook 60s sliding-window rate limit (429 over) → JSON body parse (non-JSON wraps with `_raw_body` or `_raw_body_base64`) → async `asyncio.create_task` dispatch → 202 returned immediately. `GET /health` for operator probes. (Phase 15)
- **Webhook→skill and webhook→prompt-template bindings** — skill binding fires a `Run the <skill> skill` template with payload + filtered headers (X-GitHub-Event etc.) as JSON code blocks; auth headers stripped. Prompt template binding substitutes `{{ payload }}` / `{{ headers }}` (whitespace-tolerant). Each fire spawns a one-off Agent (stateless — no session pooling). (Phase 15)
- **Delivery routing** for webhook responses: `log` / `none` / `file:<path>` (append with `--- webhook <id> <iso-ts> ---` delimiters, parent dirs auto-created) / `gateway://<platform>/<chat_id>` (routes through the running daemon's adapter). Missing daemon / missing adapter / malformed target / send failure all log without raising. (Phase 15)
- **Idempotency keys + sliding-window rate limiting** per webhook. Idempotency cache keyed on `(webhook_id, key)` so the same idempotency value across different webhooks doesn't collide; lazy-purge implementation, thread-safe under contention. Rate limiter per id so one noisy webhook hitting its budget doesn't starve others. (Phase 15)
- **HMAC compare uses `hmac.compare_digest`** (constant-time). Accepts both `X-Webhook-Signature: <hex>` (athena native) and `X-Hub-Signature-256: sha256=<hex>` (GitHub) so the same URL serves a GitHub repo and a custom client without operator-side branching. (Phase 15)
- `athena webhook {add, list, info, remove, enable, disable, test}` CLI. `add` auto-generates a 32-byte hex secret when `--secret` is omitted (HMAC/Bearer modes). `test <id>` POSTs a synthetic (or `--payload-file`-supplied) payload to the configured URL, signed per the webhook's `auth_type`; surfaces the HTTP response so the operator can verify auth + dispatch work end-to-end before pointing a real source at the URL. (Phase 15)
- `aiohttp>=3.9` added to `[gateway]` extras explicitly. (Phase 15)
- `[gateway.webhooks]` config section: `enabled` (default False — opt-in), `host` (default 127.0.0.1), `port` (default 4747). (Phase 15)

- **Multi-profile isolation** under `~/.athena/profiles/<name>/`. Each profile is its own configuration, skill set, memory, session store, cron schedule, gateway routes, MCP server set, and goal — `personal` and `work` run side-by-side without crosstalk. Sessions in one profile can't be searched from another; memory and skills the same. (Phase 14)
- `athena profile {list, show, create, switch, delete, rename}` CLI — `create` supports `--copy-from <name>` to clone an existing profile's contents wholesale; `delete` requires a confirm-token equal to the profile name (anti-typo); `default` is protected against delete and rename. (Phase 14)
- `--profile <name>` global flag + `ATHENA_PROFILE` env var (legacy `OCODE_PROFILE` honored). Resolution precedence: CLI flag > env var > `~/.athena/active_profile` file (set by `athena profile switch`) > `cfg.profile` from config.toml > hardcoded `"default"`. Invalid names at any step fall through to the next source rather than crashing. (Phase 14)
- One-time migration of legacy single-profile layout — items at the top of `~/.athena/` (skills, memory, sessions, sessions.db, mcp.json, goal.txt, cron.db, gateway.db, training_state.json, labels/, datasets/, models/, config.toml) move into `~/.athena/profiles/default/` on the first invocation after upgrade. Per-item failure isolation (one bad move logs + continues with the rest). Idempotent (the presence of `profiles/` after a successful run permanently short-circuits the check). (Phase 14)
- Strict profile name validation: lowercase alphanumerics + `_` + `-`, must start with an alphanumeric, max 64 chars. Rejects path traversal, shell-special chars, uppercase, leading hyphens/underscores. (Phase 14)

- **ACP server for IDE integration** — `athena acp serve` exposes athena over JSON-RPC 2.0 stdio, the Agent Client Protocol that Zed natively supports (VS Code / JetBrains have community adapters). `ACPServer` handles framing, request/notification dispatch with per-message asyncio.Task parallelism, and client-bound `send_request` with pending-future tracking + timeout. Shutdown drains in-flight dispatches with a 5s grace then cancels, and resolves every pending client-bound future with `ACPError` so callers in `permission_request` unwind rather than hang. (Phase 13)
- `StreamingSender` — typed wrapper around `send_notification` for the ACP streaming primitives: `text_block_start` / `text_delta` / `text_block_stop`, `tool_call_start` / `tool_call_result`, `permission_request` (returns `"deny"` on any failure path: timeout, IDE error, malformed response, unknown decision), `turn_started` / `turn_completed`. (Phase 13)
- ACP method handlers via `register(server, agent_factory)`: `initialize` (returns capabilities), `session/new` (mint or use caller-supplied id, instantiate Agent in a worker thread), `session/end` (close in thread), `session/send_message` (run agent in `asyncio.to_thread`, stream final response, surface every tool_call_trace entry as a `tool_use` block, bridge approvals via `run_coroutine_threadsafe` into the loop), `session/cancel` (sets `Agent.cancel_pending`), `session/slash_command`, `models/list`. (Phase 13)
- ACP slash commands: `/steer`, `/queue` (+ `/queue clear`), `/goal` (set / show / clear) via the same `GLOBAL_STEER_QUEUE` and goal-invariant primitives the CLI's REPL slash commands use. (Phase 13)
- `Agent.cancel_pending` flag — checked between tool rounds in `_run_turn_inner`; cleared at the start of every new `run_turn`. Allows ACP `session/cancel` to abort an in-flight turn at the next safe boundary. (Phase 13)
- `athena acp serve` / `athena acp install-zed` CLI — `serve` is what the IDE spawns over stdio; `install-zed` prints the Zed `agent_servers` settings.json snippet. (Phase 13)

- **MCP HTTP/SSE transport** — `SSETransport` runs a synchronous façade over an async SSE listener + POST `/messages` channel. Auto-handles the legacy MCP SSE protocol's `event: endpoint` frame, dispatches JSON-RPC responses by id to pending sync waiters via a daemon-thread event loop, reconnects with exponential backoff (1s → 30s) on stream failure, refreshes the OAuth token in place on 401. Public API mirrors `MCPStdioClient` so the rest of athena's MCP code is transport-agnostic. (Phase 12)
- **OAuth 2.1 PKCE flow** (`athena/mcp/oauth.py`) — code verifier + S256 challenge, local one-shot HTTP callback on `127.0.0.1:<free-port>`, state validation for CSRF defense, code-for-token exchange + refresh-token grant with preservation of the prior refresh_token / scope when the provider omits them. `webbrowser.open` for the auth URL with stderr fallback. Token persistence at `~/.athena/mcp_tokens/<server_id>.json` with atomic writes (tempfile + os.replace) and POSIX mode 0600. `needs_refresh` proactive 2-minute grace window. Path-traversal-safe server_id handling. (Phase 12)
- **Transport resolver** (`athena/mcp/transport_resolver.py`) — `open_transport(server_id, config)` dispatches on the `transport` field of an mcp.json entry: `stdio` (default; constructs `MCPStdioClient`), `sse` / `http` / `http+sse` (constructs `SSETransport`, with optional OAuth config parsed from `config["oauth"]`). Loader refactored to use the resolver — existing stdio entries unaffected. (Phase 12)
- `athena mcp {list, auth, token-status, revoke, test}` CLI — operator surface for managing MCP HTTP/SSE servers. `auth` runs the OAuth flow; `token-status` humanizes expiry per server; `revoke` deletes stored tokens; `test` initializes one server and dumps its tool catalog for first-run validation. (Phase 12)

- `SignalAdapter` — Signal via signal-cli-rest-api (Docker-deployable bridge). HTTP-only; no new Python dep. Long-poll `/v1/receive`, post to `/v2/send`, base64 attachments. Text-reply approvals via `/allow` / `/deny` keyed on the sender's UUID. Exponential reconnect backoff. (Phase 11)
- `IMessageAdapter` — iMessage via BlueBubbles Server (macOS-host bridge). Socket.IO inbound via `python-socketio[asyncio_client]`, REST outbound. Handles chatGuid / handle.address normalization for both DM and group threads. Eager attachment download. Text-reply approvals. (Phase 11)
- `MatrixAdapter` — Matrix via `matrix-nio`. Reaction-based approval UI (✅ Allow / ✖ Deny) with the prompt event_id tracked back to the request id; pre-seeded reactions so users see them as tappable. E2EE supported when `matrix-nio[e2e]` (libolm) is installed; gracefully falls back to unencrypted-only otherwise. Per-profile `matrix_store/` for key persistence. Native typing notifications. (Phase 11)
- `EmailAdapter` — IMAP IDLE + SMTP via `aioimaplib` + `aiosmtplib`. text/plain preferred over text/html; HTML flattened via `beautifulsoup4` with scripts and styles stripped. Threading via `In-Reply-To` and `References` headers tracked per sender. Optional `allowed_senders` allowlist (canonical-address comparison). Approvals via `/allow` / `/deny` in the reply body. (Phase 11)
- `TextApprovalState` mixin — shared keyed (user_id → request_id) pending-approval store + `parse_approval_decision` token parser (`/allow`, `/deny`, ✅, ✖, yes, no, single-token only) for the three text-only platforms (Signal, iMessage, Email). (Phase 11)
- `athena gateway run` CLI extended to recognize all four new platforms; per-platform required-key validation reports missing settings with a clear message and skips the adapter without taking the gateway down. (Phase 11)
- `[gateway]` extras group extended: `python-socketio[asyncio_client]>=5.10` (iMessage), `matrix-nio[e2e]>=0.24` (Matrix), `aioimaplib>=2.0`, `aiosmtplib>=3.0`, `beautifulsoup4>=4.12` (Email). (Phase 11)
- `GatewayDaemon` — single asyncio-based daemon hosting platform adapters, exposing the agent to messaging platforms. Owns the session router, agent pool, approval router, and continuity manager. ``athena gateway run`` boots it in foreground. (Phase 10)
- `GatewayAdapter` base class with Hermes-faithful reliability primitives: `_active_sessions: dict[asyncio.Event]` guards + `_session_tasks: dict[asyncio.Task]` owner map, race-free guard install before `create_task`, stale-lock self-heal via `task.done()` (Hermes issue #11016), single `_pending_messages` slot with text-merging (issue #4469), interrupt-on-text vs queue-on-photo policy, bypass-command routing (`/stop|/new|/reset|/approve|/deny|/status|/restart`), command-scoped guard handoff preserving response ordering (Hermes PR #4926). (Phase 10)
- `SessionRouter` — SQLite-backed `gateway_routes` table at `<profile>/gateway.db`. Sticky `(platform, chat_id, user_id) → session_id` routing; routes persist across daemon restarts; `last_seen_at` bumps on every reuse. (Phase 10)
- `AgentPool` — async bounded LRU cache of warm Agents. Per-session instantiation locks ensure concurrent `get()` for the same id share one factory invocation; concurrent gets for different ids run in parallel. Eviction calls `Agent.close()`. (Phase 10)
- `ApprovalRouter` — async + sync bridge for dangerous-tool approvals. `request_async` (loop side) returns the user's decision via `asyncio.Future`; `request_sync` (agent worker thread side) submits via `run_coroutine_threadsafe` and blocks on `concurrent.futures.Future`. Per-platform renderer dispatch via `register_platform_renderer(platform, renderer)`. 300s default timeout with `"deny"` as safe fallback. `cancel_all` unblocks every waiter on shutdown. (Phase 10)
- `ContinuityManager` — bulk cross-platform user linking. `link_canonical(canonical_id, {platform: pid, ...})` is atomic; `unlink_canonical` drops all bindings for a user. Routing path uses these so a Telegram + Slack pair linked to the same canonical user lands on one session. (Phase 10)
- `TelegramAdapter` (aiogram>=3) — long-polling, inline-keyboard approval buttons, eager attachment download to `<profile>/gateway_attachments/telegram/<chat>/`, Markdown body rendering. (Phase 10)
- `SlackAdapter` (slack-sdk>=3.27 Socket Mode) — no public HTTPS endpoint required, Block Kit primary/danger approval buttons, bot-self filtering via `auth.test`-discovered `_bot_user_id`, file download via httpx with the bot token in Authorization. (Phase 10)
- `DiscordAdapter` (discord.py>=2.4) — `discord.ui.View` approval buttons (callbacks bound to methods, not opaque strings), `Intents.message_content` enabled, `/athena` slash command via `app_commands.CommandTree`, `channel.typing()` for indicators. (Phase 10)
- Gateway agent factory (`build_agent_factory`) — pool factory that constructs an Agent bound to the daemon's shared SessionStore, replays the session's JSONL into `Agent.messages`, returns warm. (Phase 10)
- `Agent.resume_session_id` constructor kwarg + `Agent.load_history_from_session(session_id)` method for gateway resume. (Phase 10)
- `_process_message_background` impl — pool warm, typing-heartbeat task, gateway-bridge approval callback installed via ContextVar (copied into the worker thread by `asyncio.to_thread`), `agent.run_until_done` on the worker, final response chunked on paragraph/sentence/word boundaries and sent back, pending drain into a fresh task. (Phase 10)
- In-process `gateway.registry` — keyed by profile, populated on `daemon.start`. Used by cron's gateway-delivery path to find the daemon without IPC. (Phase 10)
- `athena gateway {run, routes, link, unlink, canonical-users}` CLI subcommands. (Phase 10)
- `[gateway]` optional dependencies group (aiogram, slack-sdk, discord.py) so headless installs don't pull SDKs. (Phase 10)
- `GatewayConfig` — `max_warm_agents` (50 default), `continuity` (off default), `platforms` per-adapter credentials dict. (Phase 10)

- Per-(provider, model_glob) tool-call parser registry under `athena/providers/parsers/` — first-match-wins with `register()` and provider-default fallthrough via `register_default()`; `resolve_parser(provider, model)` returns the function `Provider.parse_tool_calls` delegates to (Phase 9)
- Native-format parsers: `anthropic_xml` (content-block array → text + tool_use), `openai_function` (legacy `function_call` for gpt-3.5*/gpt-4-0613), `openai_tools` (current `tool_calls` for gpt-4*/4o/o1/o3/o4 and every OpenAI-compatible service), `ollama_native` (provider-default for Ollama) (Phase 9)
- Content-leak recovery parsers: `qwen_xml_leakage` (`<tool_call>{...}</tool_call>` XML), `harmony` (GPT-OSS three-channel analysis/commentary/final), `code_fenced_json` (` ```json ``` ` blocks), `json_block` (whole-content bare JSON) — model-specific globs route Qwen and GPT-OSS variants to the right parser regardless of host provider (Phase 9)
- `fallback_parser` — last-resort native `tool_calls` extractor that never raises and tolerates malformed JSON args, non-dict tool calls, missing names, and non-string IDs (Phase 9)
- Agent loop recovers leaked tool calls from streamed text via `_recover_tool_calls_from_text`, which calls `provider.parse_tool_calls` first and falls through to the generic recovery only on hard failure (Phase 9)
- Parser fixture corpus at `tests/fixtures/tool_call_outputs/<provider>/<model>/{normal,content_leakage,malformed}/` + parametrized corpus-driven test asserting every parser reproduces the captured `.expected.json` (Phase 9)
- Fuzz test: 12 (provider, model) combos × 1000 random strings + 200 random nested raw_response dicts, fixed seed, asserting parsers never raise and always return well-shaped output (Phase 9)
- `Provider` ABC, `StreamChunk` shape, and name-keyed registry under `athena/providers/` (Phase 8)
- `OllamaProvider` (replaces `OllamaClient`) on the new ABC; `ollama_client.py` is now a back-compat shim (Phase 8)
- `AnthropicProvider`, `OpenAIProvider`, `GoogleProvider` first-class providers with respx-mocked SSE parsing (Phase 8)
- `OpenAICompatProvider`, `OpenRouterProvider`, `NousProvider` — thin OpenAI-compat subclasses for vLLM/llama.cpp/openrouter.ai/portal.nousresearch.com (Phase 8)
- `CredentialPool` at `~/.athena/credentials.json` — per-provider round-robin with cooldown on 429, atomic JSON persistence, thread-safe, redacted listing (Phase 8)
- `resolve_provider(model, cfg, pool)` runtime resolver — prefix routing (anthropic/ openai/ google/ openrouter/ nous/), gemini- bare prefix, host:port/model → openai_compat, default ollama (Phase 8)
- Provider fallback chain via `providers.<primary>.fallback = ["openrouter", ...]` — resolver walks the chain when the primary has no credential or every credential is in 429 cooldown. Entries can be bare provider names (model string passes through) or `{provider, model}` dicts for cases where the model name needs to change too (Phase 8)
- `athena providers {list,test,add-key,remove-key,models}` CLI (Phase 8)
- `list_models()` on every hosted provider — `athena providers models <name>` queries the live catalog so users don't guess at stale model names (Phase 8)
- `respx>=0.21` added to `[dev]` extras for httpx mocking in provider tests (Phase 8)
- Trajectory extraction + auto-classifier (`good` / `bad` / `preference_pair` / `unreviewed`) (Phase 7)
- Trajectory extraction + auto-classifier (`good` / `bad` / `preference_pair` / `unreviewed`) (Phase 7)
- SFT and DPO dataset construction in JSONL with the qwen-coder chat template (Phase 7)
- Interactive trajectory review TUI with resume; labels persist to `<profile_dir>/labels/<session_id>.json` (Phase 7)
- Training runner wrapping `transform/scripts/train_lora.py` + new `train_dpo.py` (Phase 7)
- `transform/scripts/train_dpo.py` companion to the existing LoRA script (Phase 7)
- Ollama deployment helpers — Modelfile write + `ollama create`, `ollama list` parsing, model switch (Phase 7)
- `athena train {review,build-dataset,run,status}` — closed training loop CLI (Phase 7)
- `athena model {list,switch,info}` (Phase 7)
- `~/.athena/training_state.json` records every training run for `athena train status` (Phase 7)
- `[project.optional-dependencies.train]` extras group (trl, peft, transformers, datasets, accelerate, bitsandbytes) (Phase 7)
- APScheduler-backed cron with `agent` and `watchdog` modes (Phase 6)
- Cron output delivery to `log`, `file:<path>`, or `gateway://...` (gateway stub until Phase 10) (Phase 6)
- `/steer` and `/queue` in-flight redirection — synthetic user messages drained before each prompt, FIFO order (Phase 6)
- `/goal` Ralph-loop invariant persisted at `<profile_dir>/goal.txt` and injected at the end of every system prompt rebuild (Phase 6)
- `athena cron {add,list,remove,enable,disable,run-now,logs,daemon}` CLI (Phase 6)
- `GLOBAL_STEER_QUEUE` thread-safe singleton for cross-thread steer pushes (Phase 6)
- Plugin API with lifecycle hooks (Phase 5)
- `MemoryProvider` ABC; `BuiltinFileProvider` as default (Phase 5)
- Bundled `shell_audit` plugin (Phase 5)
- `athena plugins {list,enable,disable,info}` CLI (Phase 5)
- `Config.plugins` field + `~/.athena/plugins_state.json` for machine-managed enable state (Phase 5)
- Toolset-scoped tool registry (Phase 0)
- ContextVar provenance tracking (Phase 0)
- Agent.fork() as a core primitive (Phase 0)
- Per-thread approval callback for safe fork execution (Phase 0)
- tool check_fn for capability-based tool advertisement (Phase 0)
- agentskills.io-compliant skill format (Phase 1)
- Skill state machine (active/stale/archived) (Phase 1)
- Pinning and archive directory (Phase 1)
- Class-level umbrella architecture (references/templates/scripts) (Phase 1)
- skills_list, skill_view, skill_manage tools (Phase 1)
- athena import-from-hermes for Hermes Agent migration (Phase 1)
- Progressive disclosure of skill catalog in system prompt (Phase 1)
- SessionStore with JSONL persistence and SQLite FTS5 mirror (Phase 2)
- SearchSessions tool for recall (Phase 2)
- athena sessions {list,browse,search,purge} CLI (Phase 2)
- athena reindex command for rebuilding the session FTS5 index (Phase 2)
- Per-profile root at ~/.athena/profiles/<profile>/ (Phase 2)
- Complete Agent.fork() with auxiliary client and stdout/stderr capture (Phase 3)
- Post-write delta lint for .py / .pyi / .json / .yaml / .yml / .toml (Phase 3)
- ForkResult.actions extracted from structured tool results (Phase 3)
- Parent/child session lineage with fork-tree CLI browse (Phase 3)
- Per-turn background review fork (Phase 4)
- Curator with structured YAML output (Phase 4)
- Curator dry-run mode and run reports (run.json + REPORT.md) (Phase 4)
- Deterministic lifecycle transitions at session start (Phase 4)
- .curator_state persistence (Phase 4)
- Provenance enforcement in skill_manage by write_origin (Phase 4)
- athena curator {run, status, pause, resume, inspect-last} CLI (Phase 4)

### Changed
- README install instructions point at `pip install athena-coder` from PyPI (T1-02.7); source-install path retained for development under a separate sub-section
- Documentation reconciled with shipped code: MCP transport, sub-agent capability, phase-status markers, Modelfile system prompt (T1-05)

### Removed
- Legacy `ocode` console-script alias from `pyproject.toml` `[project.scripts]`. Update any shell aliases or scripts that called `ocode` to call `athena` instead. (T1-02)

### Security
- Credential file writes use `os.open(O_EXCL, 0o600)` atomically via the new `athena.safety.secure_files` module (T1-06)
- TOCTOU windows closed across `credential_pool.py`, `mcp/oauth.py`, and `migration/config_translator.py` (T1-06)
- `~/.athena/` subdirectories holding secret material created at `0o700` via `ensure_secure_dir`; existing wider-mode directories emit a `WARNING` rather than being silently re-chmodded (T1-06)
- Path security module sandboxes `file_ops.py` to the workspace by default; outside-workspace reads and writes require explicit approval (`(tool_name, args) -> "allow"|"deny"` callback). Absolute-deny patterns refuse `/proc/*/mem`, `/proc/kcore`, `/dev/{mem,kmem,port}`, `/dev/sd[a-z]*`, `/dev/nvme*`, `/sys/firmware/efi/efivars/*`, and the Windows raw-device equivalents regardless of approval. (T1-07)
- `athena.safety.allow_external()` context manager for legitimate outside-workspace use (test fixtures, foreground tool implementations operating on user-supplied absolute paths) (T1-07)
- Forks re-pin `path_security` workspace inside their daemon thread; combined with `AUTO_DENY` they cannot escape the parent's workspace (T1-07)
- SSRF defense on the web tool: `WebFetch` and SearxNG search backends route through `athena.safety.url_safety.validate_url`. Block list covers RFC1918 (10/8, 172.16/12, 192.168/16), loopback (127/8, ::1), link-local (169.254/16, fe80::/10), carrier-grade NAT (100.64/10), AWS IMDSv2 IPv6 metadata, IPv6 ULA (fc00::/7), multicast (224/4, ff00::/8), and IPv4-mapped IPv6 variants. (T1-08)
- Redirect `Location:` headers re-validated through `validate_url` via an httpx event hook (T1-08)
- `athena.safety.allow_external_urls()` context manager for legitimate private-IP fetches (self-hosted SearxNG, test HTTP servers) (T1-08)


- Project renamed `ocode` → `athena`. The Python package, the `athena`
  CLI command, `~/.athena/` config home, and the `ATHENA.md` project
  context file all move together. The legacy `ocode` CLI entry stays
  as an alias for one release; `~/.athena/` falls back to reading
  `~/.ocode/` when the new home doesn't exist; `ATHENA.md` falls back
  to `OCODE.md`; `OCODE_*` env vars (`MODEL`, `SESSIONS_FSYNC`,
  `SEARCH_BACKEND`, `SEARXNG_URL`, `WEB_TIMEOUT`, `WEB_USER_AGENT`,
  `HOOK_EVENT`, `TOOL_NAME`) are still honored alongside the canonical
  `ATHENA_*`.

- Legacy `~/.athena/{skills, memory, sessions, ...}` now live under `~/.athena/profiles/default/`. Auto-migrated on first run; no operator action required. `credentials.json`, `mcp_tokens/`, `plugins/`, `plugins_state.json`, `logs/` deliberately stay at `~/.athena/` (user-scope, not profile-scope) — a user's API key is a user resource, and cooldown state shared globally mirrors upstream rate-limit reality more accurately than per-profile isolation would. (Phase 14)
- Forks inherit the parent's `profile` field via `dataclasses.replace`. The invariant is now locked in by a regression test (`test_fork_inherits_parent_profile`). (Phase 14)

- `cron.delivery` — `gateway://<platform>/<chat_id>` delivery target now dispatches through the running `GatewayDaemon`'s adapter via the in-process registry. Falls back to log on missing daemon / missing adapter / loop not running. (Phase 10)

- `tomli-w>=1.0` added as a runtime dep (used by `athena model switch`) (Phase 7)
- `apscheduler>=3.10` + `sqlalchemy>=2.0` added as runtime dependencies (Phase 6)
- Agent loop drains pending steers via `_inject_pending_steers()` before each user prompt (Phase 6)
- `build_system_prompt` accepts an optional `goal` parameter and appends the invariant block last (Phase 6)
- `athena/memory.py` refactored into the `athena/memory/` package; legacy workspace-keyed API preserved (Phase 5)
- Agent loop fires plugin lifecycle hooks (`on_session_start`, `on_user_message`, `pre_tool_call`, `post_tool_call`, `on_assistant_message`, `on_session_end`); the existing settings.json hook system in `athena/hooks.py` is unchanged and runs alongside (Phase 5)
- Sub-agent dispatch tool now calls Agent.fork() under the hood
- athena/agent.py split into athena/agent/{core,fork}.py
- athena/skills/ (slash-command handlers) renamed to athena/commands/ to free
  the name for the new file-based skill format
- Agent.run_turn now persists every user / assistant / tool message to the
  session store (JSONL + SQLite FTS5)
- Hermes sessions_importer drives SessionStore so imports land in
  `athena sessions list` and FTS5 search

### Fixed

- **Anthropic message translation** — provider was sending Athena's Ollama-shaped message log (`role:"tool"` for results, `tool_calls` array on assistant turns) straight to `/v1/messages`, which 400'd with `"Unexpected role 'tool'"`. New `_translate_messages` pass converts to Anthropic's content-block shape: assistant turns become `[{"type":"text"},{"type":"tool_use",...}]`, consecutive tool results coalesce into one `role:"user"` message with `tool_result` blocks, missing `tool_use_id` values synthesize paired ids between adjacent call/result turns. Empty assistant turns are dropped entirely (Anthropic rejects empty content arrays AND empty-text blocks). 10 translation tests pin the contract. Surfaced driving Sonnet 4.6 through the calculator e2e and the curator dogfood; same task that took qwen3-coder:30b 130s now completes in 10s.
- **Cross-provider token usage accounting** — `Agent.run_turn` hardcoded Ollama's field names (`prompt_eval_count` / `eval_count`) when accumulating into `Stats`, silently zeroing the counters for every hosted provider whose usage chunk uses the OpenAI convention (`prompt_tokens` / `completion_tokens`). Accept both shapes so `athena status`, the `/cost` slash command, the audit-log cost attribution, and the closed training loop's session-efficiency scoring all keep working without per-provider branching at the call site. Caught by `athena status` reporting `0/0/0` after a Sonnet run that consumed real tokens.
- **Connect-side `OLLAMA_HOST=0.0.0.0` rewrite** — `0.0.0.0` is a server-side *bind* address (Ollama documents it for `ollama serve`); users routinely copy the same env into their client shell and hit `WinError 10049 — requested address is not valid in its context` (Windows) or `EADDRNOTAVAIL` (Linux). `_normalize_ollama_host` now rewrites `0.0.0.0` → `127.0.0.1` and `[::]` → `[::1]` while preserving scheme, port, and pass-through for already-valid hosts. 10 parametrized tests cover IPv4/IPv6 wildcards, scheme-less inputs, and remote-host passthrough.
- **cp1252-safe console output** — `ui.error`'s `✗` glyph (and `↳`, `▰`, etc.) crashed `console.print` with `UnicodeEncodeError` on legacy Windows consoles whose default stdout encoding is cp1252. `athena.ui` now reconfigures `stdout`/`stderr` with `errors="replace"` on win32 and falls back to ASCII variants of the colored unicode symbols when Rich detects the legacy Windows console, so unrepresentable characters degrade to `?` instead of taking down the process.
- **TOML loader merges into typed dataclass fields** — the naive `setattr` loop overwrote `Config.gateway` (a `GatewayConfig` dataclass) with a plain dict when the user had a `[gateway.platforms.telegram]` table; the gateway daemon then crashed on boot with `AttributeError: 'dict' object has no attribute 'continuity'`. `_assign_field` merges TOML tables into the existing dataclass instance field-by-field (recursing one level for nested dataclasses like `GatewayConfig.webhooks`), so unspecified options keep their defaults and downstream code keeps its typed attribute access. 4 new tests pin the merge behavior incl. partial override + unknown-key tolerance.
- **Tool-call parser handles "preamble + naked JSON"** — qwen2.5-coder:14b (and similar coder models) routinely emit a one-line natural-language preamble followed by `{"name": "...", "arguments": {...}}` with no `<tool_call>` wrapper or code fence. `_extract_text_tool_calls` previously handled `<tool_call>` tags, code fences, and whole-text JSON, but missed this exact shape and silently dropped the call. New brace-balanced scan picks up the first balanced `{...}` and accepts it when `_normalize_tool_call` recognizes the shape (name + arguments). Conservative: only matches objects with the tool-call shape, so prose containing literal JSON examples doesn't trip it.
- **Agent.__init__ strips routing prefixes when a provider is passed** — when `fork()` built an auxiliary client and reused the parent's prefixed model name (e.g. `"anthropic/claude-sonnet-4-6"`), the prefix went on the wire and Anthropic answered 404 not_found_error. Apply `_bare_model` unconditionally during `Agent.__init__` so the agent's on-the-wire model is always normalized, whether the provider was resolved internally or passed in.
- **Curator headless dogfood path** — `athena curator run --force` against a hosted provider surfaced three additional bugs: the `SimpleNamespace` agent shell was missing `.messages` (fork crashed with AttributeError), the curator fork was called with an empty `user_prompt` so hosted providers responded with empty content (rejected as malformed YAML), and the orchestrator's malformed-output diagnostic conflated "fork error", "empty response", and "schema drift" into a single warning that told the operator nothing. Shim now carries `messages=[]`, curator synthesizes a minimal "Begin the consolidation pass" user turn, and the rejection diagnostic splits the three failure modes so the operator sees which one fired. Validated end-to-end: Sonnet 4.6 fork under `write_origin=curator` correctly emits PRUNE for a placeholder skill while leaving foreground-authored skills untouched (Phase 4 hard rule respected).
- **Skill name validator emits actionable error** — kebab-case enforcement (`^[a-z0-9]+(?:-[a-z0-9]+)*$`) silently dropped skills with snake_case directory names at session start. Error message now detects underscores and uppercase letters in the rejected name and suggests the corrected form (e.g. `"use hyphens instead of underscores (try 'string-utils-style')"`). Behavior unchanged; purely diagnostic. Surfaced driving Sonnet through a multi-file workspace e2e where the workspace skill was being skipped and the model never followed its conventions.

## [0.1.x] - earlier

_See git history for pre-0.2.0 work._
