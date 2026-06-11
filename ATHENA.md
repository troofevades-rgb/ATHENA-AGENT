# Project: athena

## Stack
- Python 3.10+, httpx, rich, prompt_toolkit, pyyaml, tomli-w,
  apscheduler, sqlalchemy
- Talks to local Ollama at $OLLAMA_HOST (default http://localhost:11434)
- Phase 7 training extras: `pip install -e ".[train]"` — trl, peft,
  transformers, datasets, accelerate, bitsandbytes (GPU only)

## Build/test
- `pip install -e .` (editable install — required so source edits
  take effect without reinstall)
- `pytest tests/ -q`
- `pytest tests/ --cov=athena.skills --cov=athena.migration -q` for coverage

## Credentials
- `~/.athena/.env` is the single source of truth for API keys.
  Loaded once per process and cached. Format is `KEY=value` per line;
  `#` comments and blank lines OK; surrounding `'` / `"` quotes
  stripped. Recommend mode 0o600.
- Lookup order at runtime (`athena/env.py:get_credential`):
  1. `~/.athena/.env`
  2. `os.environ`
  3. Legacy `<thing>_path` config keys (file containing the raw value)
- Conventional key names:
  - `ATHENA_XAI_API_KEY` — xAI / Grok Imagine video gen (from console.x.ai)
  - `ATHENA_X_BEARER_TOKEN` — X (Twitter) v2 search API
  - `ATHENA_DISCORD_BOT_TOKEN` — Discord gateway adapter
  - `ATHENA_RUNWAY_API_KEY`, `ATHENA_PIKA_API_KEY` — future video backends
  Each backend can declare its own `credential_env_vars` tuple; the
  /video status display reads that declaration.

## Layout
- athena/agent/           agent subpackage
  - core.py              `Agent` class and the main run-turn loop
  - fork.py              `Agent.fork()` — daemon-thread sub-agents (used by
                         the `Agent` tool, background review, and the curator).
                         Captures stdout/stderr to ForkResult.{stdout,stderr};
                         extracts structured actions from tool results; binds
                         AUTO_DENY and write_origin for the fork's thread.
  - auxiliary_client.py  per-fork client factory (avoids sharing parent's KV cache)
- athena/provenance.py    write-origin ContextVar (foreground / background_review
                         / curator / migration / system) — every tool call runs
                         under a known origin
- athena/safety/approval_callback.py
                         per-thread approval callback ContextVar; forks install
                         `AUTO_DENY` so they cannot deadlock on prompts
- athena/skills/          file-based skill format (agentskills.io standard)
  - frontmatter.py       parse/serialize SKILL.md with deterministic YAML
  - discovery.py         walks ~/.athena/skills/ + <workspace>/.athena/skills/
  - loader.py            on-demand body + references/templates/scripts reads
  - manager.py           create/patch/delete/pin/unpin/write_file CRUD
  - state_machine.py     deterministic active → stale → archived transitions
  - archive.py, pin.py   destination-collision-safe moves + frontmatter flips
  - progressive_disclosure.py
                         one-line-per-skill catalog injected into the system
                         prompt at session start
  - validation.py        validate_skill(dir) → list of error strings
- athena/commands/        slash-command handlers (/loop, /compact, /resume,
                         /plan, /init, /memory, /review, /steer, /queue,
                         /goal, /subgoal, /board, /video). Full list in
                         the "Slash commands" section below. Renamed
                         from athena/skills/ in Phase 1.
- athena/review/          per-turn background review
  - nudge.py             per-session counter, fires every N tool calls
  - orchestrator.py      maybe_fire_review — spawns daemon-thread fork
  - prompts.py           Hermes-adapted MEMORY_REVIEW / SKILL_REVIEW / COMBINED
  - summary.py           bucket ForkAction → memory_writes / skill_changes
- athena/curator/         7-day umbrella consolidation pass
  - orchestrator.py      maybe_run_curator with interval+idle+paused gates
  - prompts.py           CURATOR_REVIEW_PROMPT + DRY_RUN_BANNER
  - state.py             .curator_state persistence (last_run_at, run_count, paused)
  - yaml_output.py       parse the curator's structured yaml-curator-report
  - reports.py           run.json + REPORT.md + fork-stdout.log per run
  - dry_run.py           dry-run helpers
- athena/sessions/        per-profile session persistence
  - jsonl.py             append-only JSONL primitives (truth-of-record)
  - sqlite_index.py      SQLite FTS5 mirror (schema + search)
  - store.py             SessionStore facade + UUIDv7 session IDs
  - reindex.py           rebuild sessions.db from JSONL files
- athena/migration/       one-way Hermes → athena v2 importer
  - hermes_import.py     orchestrator
  - skills_mapper.py     skills + .archive/
  - memory_exporter.py   memory.db → per-row markdown
  - sessions_importer.py jsonl + meta sidecar
  - config_translator.py config.yaml → config.toml + credentials.json
  - mcp_translator.py    mcp.json (disables http/sse pending Phase 12)
  - report.py            REPORT.md + summary.json writer
- athena/cli/             non-REPL subcommands
  - import_hermes.py     `athena import-from-hermes` (Phase 1)
  - sessions.py          `athena sessions {list,browse,search,purge}` (Phase 2)
  - reindex.py           `athena reindex` (Phase 2)
  - curator.py           `athena curator {run,status,pause,resume,inspect-last}` (Phase 4)
  - plugins.py           `athena plugins {list,enable,disable,info}` (Phase 5)
  - cron.py              `athena cron {add,list,remove,enable,disable,run-now,logs,daemon}` (Phase 6)
  - model.py             `athena model {list,switch,info}` (Phase 7)
  - train.py             `athena train {review,build-dataset,run,status}` (Phase 7)
- athena/providers/       provider abstraction (Phase 8) — `Provider` ABC,
  `StreamChunk`, name-keyed registry, runtime resolver with prefix routing
  (`anthropic/`, `openai/`, `google/`, `openrouter/`, `nous/`) and 429-aware
  fallback chains. First-class providers: `OllamaProvider`,
  `AnthropicProvider`, `OpenAIProvider`, `GoogleProvider`, `OpenAICompat`,
  `OpenRouterProvider`, `NousProvider`.
  - credential_pool.py   thread-safe per-provider key rotation; cooldown
                         on 429; atomic JSON persistence at
                         `~/.athena/credentials.json`
  - parsers/             per-(provider, model_glob) tool-call parser registry
                         (Phase 9): anthropic_xml, openai_function,
                         openai_tools, ollama_native, qwen_xml_leakage,
                         harmony, code_fenced_json, json_block, fallback
- athena/ollama_client.py  back-compat shim re-exporting OllamaProvider
- athena/plugins/         agentskills.io-style plugin format (Phase 5)
  - base.py              `Plugin` ABC with lifecycle hooks (install / session
                         start+end / pre+post tool call / user+assistant message)
  - manifest.py          `plugin.toml` parser with name/version/depends_on
  - discovery.py         walks athena/plugins/bundled/ + ~/.athena/plugins/
  - loader.py            dynamic-import + topo-sort + first-time on_install track
  - hooks.py             `HookDispatcher` — try/except per call, FIFO veto on
                         pre_tool_call, chained on_user_message
  - bundled/             plugins that ship in the package
    - shell_audit/       JSONL log per session for every Bash tool call
- athena/memory/          persistent memory (Phase 5 made it a package)
  - __init__.py          empty after R2 stage 5; legacy workspace-keyed API
                         (load_memory_index, list_memories, write_memory,
                         delete_memory, _slugify, MemoryFile) retired
  - store.py             profile-keyed facade over the active MemoryProvider
                         (load_index, write_entry, list_entries, read_entry,
                         delete_entry, query, memory_dir); the canonical
                         entry point
  - providers/base.py    `MemoryProvider` ABC + `MemoryEntry`
  - providers/builtin_file.py
                         Markdown-on-disk + SQLite ordering mirror under
                         `<profile_dir>/memory/`; reconcile-on-read handles
                         external edits
- athena/cron/            APScheduler-backed scheduled jobs (Phase 6)
  - jobs.py              `CronJob` dataclass + SQLite-backed `JobStore` for
                         metadata (separate from APScheduler's trigger store)
  - scheduler.py         `CronScheduler` — start/stop + add/remove/enable/disable;
                         re-registers every enabled job at start()
  - watchdog.py          script-only execution path with 300s timeout + 8KB
                         stdout/stderr cap
  - runner.py            agent-mode: constructs a fresh Agent and runs one
                         turn capped at 20 iterations
  - delivery.py          routing: log | file:<path> | gateway://... (Phase 10)
- athena/steer/           in-flight redirect queue (Phase 6)
  - queue.py             thread-safe per-session `SteerQueue`; module-level
                         `GLOBAL_STEER_QUEUE` for cross-thread access (Phase 10
                         gateway adapters will push to it)
- athena/goal/            Ralph-loop invariant + active driver (Phase 6+)
  - invariant.py         get/set/clear of `<profile_dir>/goal.txt`;
                         format_for_system_prompt produces the block injected
                         at the END of every system-prompt rebuild
  - state.py             `GoalState` dataclass (text/status/turns_taken/
                         max_turns/subgoals/goal_id) persisted as
                         `<profile_dir>/goal_state.json`
  - loop.py              sentinel scanner (GOAL ACHIEVED / GOAL BLOCKED)
                         + `maybe_continue_goal_after_turn` driver +
                         `build_continuation_prompt` (stitches goal text,
                         turn counter, subgoal pointer, decompose hint
                         into every synthetic continuation) +
                         `run_goal_verifier` (optional shell-command
                         gate on GOAL ACHIEVED claims via
                         `cfg.goal_verifier_command`)
- athena/videogen/        async video-generation orchestration (Phase 6.5)
  - job.py               `GenerationRequest` / `JobHandle` /
                         `CostEstimate` types + `resolve_backend(cfg)`
                         which honors `cfg.video_backend` selector first,
                         then capability broker
  - backends/stub_local.py  placeholder backend (writes a fake .mp4 for
                         smoke tests; no creds needed)
  - backends/xai.py      xAI Grok Imagine adapter — submit/poll/fetch
                         against `api.x.ai/v1/videos/generations`.
                         Reads `ATHENA_XAI_API_KEY` from .env. Declares
                         `credential_env_vars` so /video status shows
                         accurate auth state.
  - tools.py             `video_generate` + `animate_image` model-facing
                         tools. Use `get_current_agent().cfg` so
                         session-scoped `/video set` mutations are
                         visible immediately.
- athena/transform/       closed training loop (Phase 7)
  - classifier.py        `Trajectory` + `extract_trajectories` + conservative
                         `auto_classify` (good / bad / preference_pair /
                         unreviewed)
  - dataset.py           build_sft_dataset / build_dpo_dataset / write_jsonl;
                         qwen-coder chat template
  - review.py            `ReviewSession` walks unreviewed trajectories;
                         persists labels to <profile_dir>/labels/<session>.json
  - runner.py            subprocess wrappers for transform/scripts/{train_lora,
                         train_dpo,export_to_ollama}.py — uses each script's
                         existing flag names
  - deploy.py            Modelfile write + `ollama create` + switch_model
                         (writes config.toml via tomli_w)
- athena/tools/           built-in model tools
  - registry.py          toolset-scoped registry; tools declare a `toolset`
                         and optional `check_fn` for capability-based gating
  - skill_tools.py       skills_list, skill_view, skill_manage (toolset=skills)
  - recall_tools.py      search_sessions (toolset=recall)
  - delta_lint.py        post-write syntax check for .py/.pyi/.json/.yaml/.yml/.toml
  - agent_tool.py        sub-agent dispatch (thin wrapper around `Agent.fork()`)
- athena/mcp/             MCP integration. Both **stdio** and
                          **HTTP/SSE** transports supported (Phase 12).
                          HTTP/SSE with OAuth 2.1 PKCE; tokens persist at
                          `~/.athena/mcp_tokens/<server_id>.json` (mode 0600,
                          atomic writes via tempfile + os.replace).
                          Transport selected per-server via the
                          `transport_resolver` based on `mcp.json` entry's
                          `transport` field; legacy stdio entries unaffected.
- athena/safety/          mechanical safety subsystem (Phase 17)
  - approval_callback.py per-thread approval callback ContextVar; forks
                         install `AUTO_DENY`
  - approval_guard.py    ContextVar-scoped approval grants;
                         `ApprovalDeniedInBackground` raised when a fork
                         tries to prompt
  - snapshots.py         content-addressed tarball snapshots under
                         `~/.athena/snapshots/YYYY/MM/DD/`
  - audit.py             append-only JSONL mutation log at
                         `~/.athena/audit/mutations-YYYY-MM.jsonl`
  - mutation.py          `snapshot_and_record(paths, *, tool_name)`
                         combined context manager used at every skill/
                         memory mutation site
  - context.py           per-profile singletons for snapshot store +
                         audit log
  - shell_policy.py      word-boundary allowlist + always-on denylist
                         applied to every Bash command before execution
- athena/profiles/        multi-profile isolation under
                          `~/.athena/profiles/<name>/` (Phase 14). Each
                          profile owns its own skills, memory, sessions,
                          cron schedule, gateway routes, MCP servers,
                          and goal. Strict name validation; default is
                          delete-protected.
- athena/gateway/         messaging-platform daemon (Phase 10-11). Owns the
                          session router, agent pool, approval router, and
                          continuity manager. Adapters under
                          `athena/gateway/platforms/` for Telegram, Slack,
                          Discord, Signal, iMessage, Matrix, Email — each
                          renders approvals natively (inline buttons,
                          reactions, or text-reply tokens).
- athena/acp/             Agent Client Protocol server (Phase 13) exposing
                          athena to Zed and other ACP IDEs over JSON-RPC 2.0
                          stdio.
- athena/webhooks/        HTTP webhook listener inside the gateway daemon
                          (Phase 15). HMAC-SHA256 / Bearer / none auth,
                          idempotency cache, per-webhook sliding-window
                          rate limiting, skill / prompt-template bindings.
- athena/prompts/         system-prompt builder. Composes the Modelfile
                          SYSTEM, project ATHENA.md, skills catalog, goal
                          invariant, and progressive disclosure into the
                          single string seeded as messages[0].

### Remaining subpackages (one-line map)

The packages above get detailed treatment because changes routinely
touch them. The rest of the tree, for completeness (every top-level
`athena/<pkg>/` must appear here — see the "Don't" rule in CLAUDE.md):

- athena/recall/          semantic recall — past turns + memory embedded
                          into a local vector index, auto-injected when
                          `recall_auto` is on (doc_id = `<session>#<turn>`)
- athena/user_model/      auto-extracted observations about the user,
                          written as profile-scoped markdown facts
- athena/cache/           cross-session prompt caching (T5-06)
- athena/proxy/           `athena proxy` — local OpenAI-compatible HTTP
                          endpoint that fronts the provider abstraction
- athena/sandbox/         optional bwrap sandbox for the Bash tool; the
                          shell_policy denylist remains the floor when off
- athena/verify/          verified-execution loop (run → observe → repair)
- athena/lsp/             LSP diagnostics surface, used by verify-on-write
- athena/eval/            eval battery (agent task suites + scoring)
- athena/jailbreak/       godmode strategy + race source-of-truth (gated by
                          `ATHENA_ALLOW_GODMODE`; see `/godmode`)
- athena/headless/        headless one-shot run primitive (`athena -p`)
- athena/batch/           batch runner over many prompts (`athena batch`)
- athena/delegate/        delegation to external coding CLIs (codex, etc.)
- athena/tasks/           auto-kanban task store + board projection (`/board`)
- athena/tui_gateway/     Python↔Ink-TUI bridge: spawns the bundled JS,
                          speaks the JSON-RPC protocol over a per-launch
                          token-authenticated socket (UDS on POSIX, TCP on
                          Windows); schema in `tui_gateway/schema/`
- athena/update/          self-update (detect install method → git/pip path)
- athena/social/          social provider integration (X/Twitter search)
- athena/media/           media broker shared by the perception stack
- athena/vision/          image analysis (tiled passthrough to the provider)
- athena/ocr/             OCR — text from images / scanned pages
- athena/audio/           audio analysis + transcription (faster-whisper);
                          TTS backends live under `audio/tts/`
- athena/video/           video analysis (frame sampling → vision)
- athena/document/        document parsing (pdf/docx extractors)
- athena/browser/         persistent-CDP browser automation (Playwright)
- athena/computer/        computer use — desktop screenshot + control,
                          opt-in with tiered approval
- athena/skills_default/  skills that ship in the wheel, seeded on first run
                          (excluded from lint/mypy/coverage by design)

Top-level modules: `provenance.py`, `config.py` / `config_sections.py` /
`config_deprecations.py`, `env.py`, `net.py`, `text_utils.py`, `ui.py`,
`ollama_client.py` (back-compat shim), and the observability rails
`boot_trace.py` / `crash_log.py` / `event_log.py` / `interrupt_hooks.py`.

## Conventions
- New built-in tools register via `@tool(name=…, toolset=…, …)` in `athena/tools/`
- Toolsets group tools by capability surface. `enabled_toolsets` scopes which
  tools the model sees; forks always pass an explicit list.
- Every tool call runs under a known `write_origin` — read it from
  `athena.provenance.get_current_write_origin()` when recording who did what.
- Skills are directories under `~/.athena/skills/` or
  `<workspace>/.athena/skills/`, each with a SKILL.md + optional
  `references/`, `templates/`, `scripts/` subdirs. State and pinned flag
  live in the SKILL.md frontmatter; the file is the source of truth.
- Migration writes always run under `write_origin="migration"` so the curator
  can identify imported content and leave it alone until it sees local activity.
- Plugins (Phase 5) are directories under `athena/plugins/bundled/` or
  `~/.athena/plugins/` with `plugin.toml` + `plugin.py`. Each plugin is a
  subclass of `athena.plugins.base.Plugin` overriding the lifecycle hooks
  it cares about. The loader binds `name`/`version` from the manifest and
  calls `on_install()` once, tracked in `~/.athena/plugins_installed`.
  Enable state lives in `~/.athena/plugins_state.json` (machine-managed JSON);
  `config.toml` stays hand-edited.
- The agent loop fires lifecycle events through the plugin layer only.
  The legacy `athena/hooks.py` settings.json hook system was retired in
  Phase 18.1 Refactor 5; the bundled `ShellHookPlugin`
  (`athena/plugins/bundled/shell_hook/`) reads the same settings.json
  hooks block and dispatches via the plugin layer. `athena/hooks.py`
  survives one release as a deprecation shim.
- `/goal` is read at session start AND on every system-prompt rebuild
  (after `/cwd`, `/clear`, `Agent.reload_goal()` etc.) so the invariant
  is always re-injected.
- `~/.athena/config.toml` gotcha: top-level config keys MUST appear
  ABOVE any `[section]` header. TOML semantics say keys after a
  section header belong to that section — so a top-level flag like
  `video_generation_enabled = true` placed after `[gateway.platforms.
  discord]` parses as `cfg.gateway.platforms.discord.video_generation_
  enabled` and the actual top-level field stays at its default.
  We've hit this twice; if a config knob seems ignored, check
  placement first.
- Tools should read the LIVE agent's cfg, not a fresh `load_config()`
  load. Use `athena.agent.core.get_current_agent()` first and fall
  back to disk only when no agent is bound. This makes session-scoped
  mutations (`/video set`, `/goal …`) visible to tool calls immediately.
- `cfg.goal_verifier_command` (optional shell command) gates `GOAL
  ACHIEVED` claims. When set, the loop runs it after the sentinel
  fires; non-zero exit refuses the achievement and feeds the output
  back to the model. Bump-counts toward `max_turns` so a model that
  keeps claiming done can't loop forever.
- Backend providers can declare `credential_env_vars: tuple[str, ...]`
  to make `/video` (and future similar status displays) show
  accurate "auth ok" / "no credential found" messages — without
  this, status falls back to a heuristic `ATHENA_<NAME>_API_KEY`
  guess that won't match if the resolver uses a different key name.

## CLI
- `athena` — interactive REPL (default)
- `athena -p "<prompt>"` — one-shot prompt
- `athena --version` — print `athena-coder <version>` and exit
- `athena --profile <name>` — pick profile (also `ATHENA_PROFILE` env)
- `athena import-from-hermes --source PATH --dest PATH [--dry-run]` —
  migrate a Hermes home into athena v2
- `athena sessions {list,browse,search,purge}` — inspect prior sessions
- `athena reindex [--profile NAME]` — rebuild the session FTS5 index from JSONL
- `athena curator run [--dry-run] [--force]` — run the umbrella consolidator now
- `athena curator {status,pause,resume,inspect-last}` — manage the curator
- `athena plugins {list,enable,disable,info}` — plugin management
- `athena cron {add,list,remove,enable,disable,run-now,logs,daemon}` —
  scheduled jobs (agent or watchdog mode)
- `athena model {list,switch,info}` — Ollama model management
- `athena train {review,build-dataset,run,status}` — closed training loop
- `athena profile {list,show,create,switch,delete,rename}` — manage
  per-profile config / skills / memory / sessions
- `athena providers {list,test,add-key,remove-key,models}` — hosted
  provider credentials + live model catalog query
- `athena mcp {list,auth,token-status,revoke,test}` — manage MCP servers
  (stdio + HTTP/SSE; OAuth flow runs locally)
- `athena gateway {run,routes,link,unlink,canonical-users}` — messaging-
  platform daemon (Telegram, Slack, Discord, Signal, iMessage, Matrix, Email)
- `athena acp {serve,install-zed}` — Agent Client Protocol server for IDEs
- `athena webhook {add,list,info,remove,enable,disable,test}` — webhook
  subscriptions hosted inside the gateway daemon
- `athena status [--profile NAME] [--json]` — read-only counters from
  `<profile_dir>/.status.json` (atomic snapshot written at every turn end)
- `athena snapshot {list,show,pin,unpin,prune}` — inspect the Phase 17
  content-addressed snapshot store
- `athena skill {diff,rollback} <name>` — diff a skill against its most-
  recent snapshot; rollback restores byte-for-byte (rollback itself audited)
- `athena memory {diff,rollback} <name>` — same for memory entries
- `athena board [--goal <id>] [--profile NAME] [--static]` — render the
  kanban for a workspace; `--static` forces plain text even when
  textual TUI is available
- `athena doctor [--no-network] [--json]` — health check (config, creds,
  ollama, providers, tui); each `[FAIL]` line names the fix
- `athena proxy` — run the local OpenAI-compatible HTTP endpoint
- `athena batch …` — run many prompts headlessly (serial or `--parallel`)
- `athena eval …` — run the eval battery
- `athena recall {backfill,…}` — manage the semantic-recall vector index
- `athena delegate …` — hand a task to an external coding CLI
- `athena verify …` — verified-execution loop entry point
- `athena audit …` — read the mutation audit log
- `athena cache …` / `athena cleanup-blobs` — prompt-cache + blob upkeep
- `athena checkpoint …` / `athena rollback …` — conversation checkpoints
- `athena theme [NAME]` — switch the TUI palette (one-shot config mutator)
- `athena image-demo` / `athena wordmark` — rendering demos

(Full subcommand list: every module in `athena/cli/` registers one.)

## Slash commands

Single dispatch path: every `/<name>` lookup goes through
`commands.get_command(name)` (the `@command(...)` decorator registry).
Each command lives in its own module under `athena/commands/<name>.py`
and registers via the decorator on import; `athena/commands/__init__.py`
side-effect imports every module so the registry is populated at
process start. `athena/__main__.py:_handle_slash` is the REPL's
adapter — it parses the line, looks up the handler, and invokes it.

**One exception:** `/exit /quit /q` are checked inline in
`_handle_slash` BEFORE the registry lookup, because they signal "break
the outer REPL loop" by returning False to the caller. The registry's
handler contract returns a string (the next user-turn prompt) or "",
which can't express "exit". Routing exit through the registry would
require a sentinel return value or an exception type; the inline check
is one branch and pays for itself.

Slash commands available in the REPL:

- `/help` — show the slash-command help block
- `/exit /quit /q` — leave the REPL (inline, see above)
- `/clear` — reset conversation (keeps system prompt)
- `/model [NAME|N]` — switch model. Bare `/model` opens a picker
  (numbered list grouped by provider; Ollama local + OpenRouter
  catalog if credentialed; non-tool-calling OpenRouter models marked
  `[no-tools]`). `/model N` picks by index from the last picker
  render. `/model NAME` is the legacy direct-switch path.
- `/models` — list models on the active provider
- `/tools` — list registered tools (built-in + MCP)
- `/mcp [logs NAME]` — list connected MCP servers; `logs <name>` dumps the
  named server's recent stderr
- `/cost` — token usage + elapsed time for this session
- `/status` — render the session snapshot (model, profile, elapsed,
  tokens, tool histogram, p50/p95/p99 turn + per-tool latencies,
  provider/tool error counters, godmode active state when set)
- `/cwd [path]` — show or change workspace
- `/save [file]` — save transcript JSON
- `/dump` — print the assembled system prompt (debug)
- `/hooks` — list configured settings.json hooks
- `/godmode` — jailbreak toolkit. Gated by `ATHENA_ALLOW_GODMODE=1`
  in `~/.athena/.env` or the process environment. Subcommands:
  `list`, `apply [strategy]` (system-prompt mutation), `steer
  [strategy]` (auditable steer-queue variant), `clear` (mode-aware
  undo), `auto [--score] [--canary <query>] [--max N]` (family-table
  pick OR canary-tested empirical pick), `race <query> [--tier
  fast|standard|smart|power|ultra|ollama-local] [--no-godmode]
  [--no-depth]` (multi-model race; ollama-local is athena-exclusive
  zero-API-cost variant), `prefill {set|clear|status}`,
  `parseltongue`, `test`, `save`, `load`. See `athena/commands/godmode.py`
  for the full surface.
- `/init` — `athena init`: scaffold ATHENA.md from a workspace survey
- `/loop INTERVAL CMD` — re-run a prompt or slash command on a timer
- `/loop-stop` — stop a running `/loop`
- `/compact` — summarize history and replace it with the summary
- `/resume [file]` — load a saved session JSONL into the current REPL
- `/memory {list,show,delete,dir}` — inspect or edit persistent memory
- `/plan [prompt]` — enter plan mode (read-only investigation); `/plan-exit`
  to leave without executing
- `/review [ref]` — review pending changes (or a git ref); `/security-review`
  for security-focused review
- `/steer MSG | /steer clear | /queue` — queue cross-thread redirects;
  delivered as synthetic user messages before your next prompt. FIFO.
- `/board` — show the kanban for the current workspace. Subcommands:
  `/board goal:<id>` filters to one goal's cards; `/board clear`
  wipes every live task (archive untouched). Use `/board clear`
  when aspirational tasks from a prior session are polluting context.
- `/video` — inspect / switch the video-generation backend:
  - `/video` (or `status` / `show`) — current selector, every
    registered backend, and auth status (reads each backend's
    declared `credential_env_vars`).
  - `/video list` — name-only listing.
  - `/video set <name>` — pin a backend for this session (mutates
    `cfg.video_backend` in memory; survives until restart). Edit
    `~/.athena/config.toml` to persist.
  - `/video clear` — unset; broker auto-picks again.
  Default backends: `stub_video_local` (placeholder, no key) and
  `xai_video` (Grok Imagine — needs `ATHENA_XAI_API_KEY` in .env).
- `/goal MSG` — set a concrete deliverable as the active goal. Vague
  text ("be the best", "ship it") is refused — must be ≥4 words and
  describe what "done" looks like. Setting auto-fires the first
  continuation turn so the loop bootstraps without a manual nudge.
- `/goal` (or `/goal status` / `/goal show`) — show current goal text,
  status, turn counter, and declared subgoals.
- `/goal pause` — stop the continuation loop (status=paused).
- `/goal resume` — restart the loop; from an exhausted state, grants
  another `cfg.goal_max_turns` (auto-bumped to 10,000 for local
  providers like ollama).
- `/goal clear` — wipe goal.txt + goal_state.json.
- `/subgoal MSG` — append a subgoal (advisory).
- `/subgoal done` — mark the first not-done subgoal complete.

Goal-loop behavior the model needs to know:
- Every synthetic continuation prompt includes the goal text, turn
  counter, and next subgoal — the model sees its objective in the
  user message every turn, not just the system prompt.
- When no subgoals exist, the continuation prompt asks the model to
  call `/subgoal <text>` 3-6 times to decompose before doing real
  work.
- Sentinels: end a message with `GOAL ACHIEVED` to claim done; with
  `GOAL BLOCKED: <reason>` to pause for user input.
- If `cfg.goal_verifier_command` is set, the verifier runs after
  `GOAL ACHIEVED` and can refuse the claim with output the model
  reads on the next turn.
- The goal text is also injected at the END of every system-prompt
  rebuild as the passive invariant.

Tool-call discipline:
- When the user asks for something a tool can do (video_generate,
  search_x, etc.), CALL THE TOOL. Don't refuse based on guessing
  whether config is set right — the tool returns structured
  `status` responses (`not_enabled`, `not_configured`, etc.) and
  you react to them. Pre-judging wastes a turn and lies to the user.
