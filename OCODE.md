# Project: ocode

## Stack
- Python 3.10+, httpx, rich, prompt_toolkit, pyyaml, tomli-w,
  apscheduler, sqlalchemy
- Talks to local Ollama at $OLLAMA_HOST (default http://localhost:11434)
- Phase 7 training extras `pip install -e ".\[train\]"` — trl, peft,
  transformers, datasets, accelerate, bitsandbytes (GPU only)

## Build/test
- `pip install -e .` (already done in .venv)
- `pytest tests/ -q`
- `pytest tests/ --cov=ocode.skills --cov=ocode.migration -q` for coverage

## Layout
- ocode/agent/           agent subpackage
  - core.py              `Agent` class and the main run-turn loop
  - fork.py              `Agent.fork()` — daemon-thread sub-agents (used by
                         the `Agent` tool, background review, and the curator).
                         Captures stdout/stderr to ForkResult.{stdout,stderr};
                         extracts structured actions from tool results; binds
                         AUTO_DENY and write_origin for the fork's thread.
  - auxiliary_client.py  per-fork client factory (avoids sharing parent's KV cache)
- ocode/provenance.py    write-origin ContextVar (foreground / background_review
                         / curator / migration / system) — every tool call runs
                         under a known origin
- ocode/safety/approval_callback.py
                         per-thread approval callback ContextVar; forks install
                         `AUTO_DENY` so they cannot deadlock on prompts
- ocode/skills/          file-based skill format (agentskills.io standard)
  - frontmatter.py       parse/serialize SKILL.md with deterministic YAML
  - discovery.py         walks ~/.ocode/skills/ + <workspace>/.ocode/skills/
  - loader.py            on-demand body + references/templates/scripts reads
  - manager.py           create/patch/delete/pin/unpin/write_file CRUD
  - state_machine.py     deterministic active → stale → archived transitions
  - archive.py, pin.py   destination-collision-safe moves + frontmatter flips
  - progressive_disclosure.py
                         one-line-per-skill catalog injected into the system
                         prompt at session start
  - validation.py        validate_skill(dir) → list of error strings
- ocode/commands/        slash-command handlers (/loop, /compact, /resume,
                         /plan, /init, /memory, /review, /steer, /queue, /goal).
                         Renamed from ocode/skills/ in Phase 1.
- ocode/review/          per-turn background review
  - nudge.py             per-session counter, fires every N tool calls
  - orchestrator.py      maybe_fire_review — spawns daemon-thread fork
  - prompts.py           Hermes-adapted MEMORY_REVIEW / SKILL_REVIEW / COMBINED
  - summary.py           bucket ForkAction → memory_writes / skill_changes
- ocode/curator/         7-day umbrella consolidation pass
  - orchestrator.py      maybe_run_curator with interval+idle+paused gates
  - prompts.py           CURATOR_REVIEW_PROMPT + DRY_RUN_BANNER
  - state.py             .curator_state persistence (last_run_at, run_count, paused)
  - yaml_output.py       parse the curator's structured yaml-curator-report
  - reports.py           run.json + REPORT.md + fork-stdout.log per run
  - dry_run.py           dry-run helpers
- ocode/sessions/        per-profile session persistence
  - jsonl.py             append-only JSONL primitives (truth-of-record)
  - sqlite_index.py      SQLite FTS5 mirror (schema + search)
  - store.py             SessionStore facade + UUIDv7 session IDs
  - reindex.py           rebuild sessions.db from JSONL files
- ocode/migration/       one-way Hermes → ocode v2 importer
  - hermes_import.py     orchestrator
  - skills_mapper.py     skills + .archive/
  - memory_exporter.py   memory.db → per-row markdown
  - sessions_importer.py jsonl + meta sidecar
  - config_translator.py config.yaml → config.toml + credentials.json
  - mcp_translator.py    mcp.json (disables http/sse pending Phase 12)
  - report.py            REPORT.md + summary.json writer
- ocode/cli/             non-REPL subcommands
  - import_hermes.py     `ocode import-from-hermes` (Phase 1)
  - sessions.py          `ocode sessions {list,browse,search,purge}` (Phase 2)
  - reindex.py           `ocode reindex` (Phase 2)
  - curator.py           `ocode curator {run,status,pause,resume,inspect-last}` (Phase 4)
  - plugins.py           `ocode plugins {list,enable,disable,info}` (Phase 5)
  - cron.py              `ocode cron {add,list,remove,enable,disable,run-now,logs,daemon}` (Phase 6)
  - model.py             `ocode model {list,switch,info}` (Phase 7)
  - train.py             `ocode train {review,build-dataset,run,status}` (Phase 7)
- ocode/ollama_client.py thin /api/chat wrapper (provider abstraction lands in Phase 8)
- ocode/plugins/         agentskills.io-style plugin format (Phase 5)
  - base.py              `Plugin` ABC with lifecycle hooks (install / session
                         start+end / pre+post tool call / user+assistant message)
  - manifest.py          `plugin.toml` parser with name/version/depends_on
  - discovery.py         walks ocode/plugins/bundled/ + ~/.ocode/plugins/
  - loader.py            dynamic-import + topo-sort + first-time on_install track
  - hooks.py             `HookDispatcher` — try/except per call, FIFO veto on
                         pre_tool_call, chained on_user_message
  - bundled/             plugins that ship in the package
    - shell_audit/       JSONL log per session for every Bash tool call
- ocode/memory/          persistent memory (Phase 5 made it a package)
  - __init__.py          legacy workspace-keyed API (load_memory_index,
                         list_memories, write_memory, delete_memory) — kept
                         byte-for-byte; agent still uses this for the system
                         prompt today
  - store.py             profile-keyed facade over the active MemoryProvider;
                         Phase 14 will migrate the legacy callers
  - providers/base.py    `MemoryProvider` ABC + `MemoryEntry`
  - providers/builtin_file.py
                         Markdown-on-disk + SQLite ordering mirror under
                         `<profile_dir>/memory/`; reconcile-on-read handles
                         external edits
- ocode/cron/            APScheduler-backed scheduled jobs (Phase 6)
  - jobs.py              `CronJob` dataclass + SQLite-backed `JobStore` for
                         metadata (separate from APScheduler's trigger store)
  - scheduler.py         `CronScheduler` — start/stop + add/remove/enable/disable;
                         re-registers every enabled job at start()
  - watchdog.py          script-only execution path with 300s timeout + 8KB
                         stdout/stderr cap
  - runner.py            agent-mode: constructs a fresh Agent and runs one
                         turn capped at 20 iterations
  - delivery.py          routing: log | file:<path> | gateway://... (Phase 10)
- ocode/steer/           in-flight redirect queue (Phase 6)
  - queue.py             thread-safe per-session `SteerQueue`; module-level
                         `GLOBAL_STEER_QUEUE` for cross-thread access (Phase 10
                         gateway adapters will push to it)
- ocode/goal/            Ralph-loop invariant (Phase 6)
  - invariant.py         get/set/clear of `<profile_dir>/goal.txt`;
                         format_for_system_prompt produces the block injected
                         at the END of every system-prompt rebuild
- ocode/transform/       closed training loop (Phase 7)
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
- ocode/tools/           built-in model tools
  - registry.py          toolset-scoped registry; tools declare a `toolset`
                         and optional `check_fn` for capability-based gating
  - skill_tools.py       skills_list, skill_view, skill_manage (toolset=skills)
  - recall_tools.py      search_sessions (toolset=recall)
  - delta_lint.py        post-write syntax check for .py/.pyi/.json/.yaml/.yml/.toml
  - agent_tool.py        sub-agent dispatch (thin wrapper around `Agent.fork()`)
- ocode/mcp/             MCP stdio integration

## Conventions
- New built-in tools register via `@tool(name=…, toolset=…, …)` in `ocode/tools/`
- Toolsets group tools by capability surface. `enabled_toolsets` scopes which
  tools the model sees; forks always pass an explicit list.
- Every tool call runs under a known `write_origin` — read it from
  `ocode.provenance.get_current_write_origin()` when recording who did what.
- Skills are directories under `~/.ocode/skills/` or
  `<workspace>/.ocode/skills/`, each with a SKILL.md + optional
  `references/`, `templates/`, `scripts/` subdirs. State and pinned flag
  live in the SKILL.md frontmatter; the file is the source of truth.
- Migration writes always run under `write_origin="migration"` so the curator
  can identify imported content and leave it alone until it sees local activity.
- Plugins (Phase 5) are directories under `ocode/plugins/bundled/` or
  `~/.ocode/plugins/` with `plugin.toml` + `plugin.py`. Each plugin is a
  subclass of `ocode.plugins.base.Plugin` overriding the lifecycle hooks
  it cares about. The loader binds `name`/`version` from the manifest and
  calls `on_install()` once, tracked in `~/.ocode/plugins_installed`.
  Enable state lives in `~/.ocode/plugins_state.json` (machine-managed JSON);
  `config.toml` stays hand-edited.
- The agent loop fires plugin hooks on top of the legacy `ocode/hooks.py`
  settings.json hook system — both run; settings hooks first, plugins second.
- `/goal` is read at session start AND on every system-prompt rebuild
  (after `/cwd`, `/clear`, `Agent.reload_goal()` etc.) so the invariant
  is always re-injected.

## CLI
- `ocode` — interactive REPL (default)
- `ocode -p "<prompt>"` — one-shot prompt
- `ocode import-from-hermes --source PATH --dest PATH [--dry-run]` —
  migrate a Hermes home into ocode v2
- `ocode sessions {list,browse,search,purge}` — inspect prior sessions
- `ocode reindex [--profile NAME]` — rebuild the session FTS5 index from JSONL
- `ocode curator run [--dry-run] [--force]` — run the umbrella consolidator now
- `ocode curator {status,pause,resume,inspect-last}` — manage the curator
- `ocode plugins {list,enable,disable,info}` — Phase 5 plugin management
- `ocode cron {add,list,remove,enable,disable,run-now,logs,daemon}` — Phase 6
  scheduled jobs (agent or watchdog mode)
- `ocode model {list,switch,info}` — Phase 7 Ollama model management
- `ocode train {review,build-dataset,run,status}` — Phase 7 closed training loop

## Slash commands (Phase 6 additions)
- `/steer <message>` — queue a redirect; delivered as a synthetic user
  message before your next prompt. FIFO; `/queue` lists pending.
- `/goal <msg|show|clear>` — set or clear the persistent invariant.
  Stored at `<profile_dir>/goal.txt`; injected at the END of every
  system-prompt rebuild.
