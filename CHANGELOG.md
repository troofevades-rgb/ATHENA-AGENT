# Changelog

## Unreleased

### Renamed
- Project renamed `ocode` → `athena`. The Python package, the `athena`
  CLI command, `~/.athena/` config home, and the `ATHENA.md` project
  context file all move together. The legacy `ocode` CLI entry stays
  as an alias for one release; `~/.athena/` falls back to reading
  `~/.ocode/` when the new home doesn't exist; `ATHENA.md` falls back
  to `OCODE.md`; `OCODE_*` env vars (`MODEL`, `SESSIONS_FSYNC`,
  `SEARCH_BACKEND`, `SEARXNG_URL`, `WEB_TIMEOUT`, `WEB_USER_AGENT`,
  `HOOK_EVENT`, `TOOL_NAME`) are still honored alongside the canonical
  `ATHENA_*`.

### Added
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

### Changed
- `cron.delivery` — `gateway://<platform>/<chat_id>` delivery target now dispatches through the running `GatewayDaemon`'s adapter via the in-process registry. Falls back to log on missing daemon / missing adapter / loop not running. (Phase 10)

### Added
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
