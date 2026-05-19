# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`ATHENA.md` at the repo root has a complete, up-to-date directory map and convention list — read it first for any non-trivial change. This file only adds Claude-Code-specific guidance that ATHENA.md doesn't cover.

## What this is

athena is a local Claude-Code-style agent that talks to Ollama instead of a hosted API. It is meta — the codebase is an agentic CLI with tool calling, sub-agent forks, background review, a 7-day curator pass, a session store, a file-based skill system, a plugin system, scheduled cron jobs, in-flight redirects (`/steer`) and a persistent goal invariant (`/goal`), and a closed training loop that turns reviewed sessions into a new Ollama model. Many changes touch several of those subsystems at once. The provider abstraction is in place: Ollama, Anthropic, OpenAI, Google, OpenAI-compat, OpenRouter, and Nous Portal are first-class providers. The credential pool at `athena/providers/credential_pool.py` rotates on 429. `OllamaProvider` is the default.

## Commands

```bash
pip install -e ".[dev]"                  # install with dev tools
pip install -e ".[train]"                # GPU-only extras for Phase 7 training
pytest -q                                # full test suite (~580 tests)
pytest tests/plugins -q                  # single subpackage
pytest tests/test_fork_full.py -q        # single file
pytest -k test_fork_captures_stdout -q   # single test by name
pytest --cov=athena.plugins --cov=athena.cron -q   # coverage for one area
ruff check athena tests                   # lint
mypy                                     # strict type-check (config in pyproject)
athena -p "fix the failing test in tests/test_prompts.py"   # one-shot dogfood run
```

`pyproject.toml` pins `mypy strict = true` for the `athena` package — new code is expected to type-check cleanly. Tests are exempt from `disallow_untyped_defs`.

## Architecture in one breath

Single agent loop (`athena/agent/core.py`) → Ollama `/api/chat` → tool dispatch through a toolset-scoped registry → loop. Layered on top of that loop:

- **Forks** (`agent/fork.py`): daemon-thread sub-agents with their own httpx client (`auxiliary_client.py`) so they don't poison the parent's KV cache. Used by the `Agent` tool, the background review fork, and the curator.
- **Provenance** (`provenance.py`): every tool call runs under a `write_origin` ContextVar (`foreground`, `background_review`, `curator`, `migration`, `system`). Anything that records who did what should read `get_current_write_origin()` rather than guess.
- **Approval callback** (`safety/approval_callback.py`): per-thread ContextVar. Forks install `AUTO_DENY` so they can't deadlock on a confirmation prompt for a tool the parent would have asked the user about.
- **Toolsets**: tools declare a `toolset=…` in `@tool(...)`. `enabled_toolsets` scopes which surface the model sees; forks always pass an explicit list. New tools must pick a toolset.
- **Session store** (`sessions/`): JSONL is the source of truth, SQLite FTS5 is a derived mirror. `athena reindex` rebuilds the index from JSONL. Don't write to the SQLite file as if it were canonical.
- **Skills** (`skills/`, agentskills.io format): directories with `SKILL.md` + optional `references/templates/scripts/`. State (`active|stale|archived`) and `pinned` live in the SKILL.md frontmatter — the file is the source of truth, not a database.
- **Background review** (`review/`): fires every N tool calls, suggests memory writes / skill changes, runs under `write_origin="background_review"`.
- **Curator** (`curator/`): 7-day umbrella consolidation pass, gated by interval + idle + paused state; emits structured YAML and a `REPORT.md` per run.
- **Plugins** (`plugins/`, Phase 5): `Plugin` ABC with lifecycle hooks (session start/end, pre/post tool call, user/assistant message). Discovered from `athena/plugins/bundled/` and `~/.athena/plugins/`. Enable state in `~/.athena/plugins_state.json`. The dispatcher catches every plugin exception so a broken plugin can never break the agent. Coexists with the legacy `athena/hooks.py` settings.json hook system — both fire on tool calls.
- **Memory** (`memory/`, became a package in Phase 5): legacy workspace-keyed API in `__init__.py` (still what the agent uses for the system prompt). New `MemoryProvider` ABC and `BuiltinFileProvider` under `memory/providers/` use a per-profile layout with a SQLite ordering mirror. Phase 14 will migrate the agent's reads off the legacy API.
- **Cron** (`cron/`, Phase 6): APScheduler with two SQLite files — `cron.db` for triggers, `cron_jobs.db` for metadata. Two modes: `agent` (full LLM-driven turn) and `watchdog` (subprocess.run with no LLM). Delivery routes: `log`, `file:<path>`, `gateway://...` (stubbed until Phase 10).
- **Steer queue** (`steer/`, Phase 6): thread-safe per-session FIFO. The agent loop drains it via `_inject_pending_steers()` before every user prompt; each pending message becomes a synthetic `{"role": "user", "content": "[/steer] <msg>"}`. A module-level singleton `GLOBAL_STEER_QUEUE` exists for cross-thread push from Phase 10 gateway adapters.
- **Goal** (`goal/`, Phase 6): single-string invariant persisted at `<profile_dir>/goal.txt`. Injected at the END of every system prompt rebuild (`build_system_prompt(goal=...)`). `/goal` mutates the file and calls `Agent.reload_goal()` to rebuild messages[0] in place — no `/clear` needed.
- **Transform** (`transform/`, Phase 7): closed training loop. Trajectories are extracted from session JSONL, auto-classified (good/bad/preference_pair/unreviewed), labeled interactively (`athena train review`), assembled into SFT and DPO JSONL, then handed to `transform/scripts/{train_lora,train_dpo,export_to_ollama}.py` via subprocess wrappers. The result is registered with Ollama under a new tag; `athena model switch` makes it the default for new sessions.

A common pitfall: `athena/skills/` is the file-based skill *format* (Phase 1). Slash-command handlers (`/init`, `/review`, `/plan`, `/memory`, `/loop`, `/compact`, `/resume`, `/steer`, `/queue`, `/goal`) live in `athena/commands/`. They were renamed apart in Phase 1; don't conflate.

Another pitfall: `athena/plugins/` (Phase 5, the `Plugin` ABC + bundled plugins) is distinct from `athena/hooks.py` (Phase 0, the settings.json hook system). Both run; plugins layer on top.

## Conventions worth internalizing

- Register a new built-in tool with `@tool(name=…, toolset=…, …)` in `athena/tools/`, then import in `athena/tools/__init__.py`. If it writes to disk, it gets post-write delta lint for free for `.py/.pyi/.json/.yaml/.yml/.toml` (`tools/delta_lint.py`).
- Don't share httpx clients across threads — use `auxiliary_client.py` factory pattern for forks.
- Migration tools (`migration/`) always write under `write_origin="migration"` so the curator leaves imported content alone until it sees local activity. Preserve that invariant.
- MCP tools come in namespaced as `{server}__{tool}` and bypass the built-in confirmation hook. If a destructive MCP tool needs gating, point the user at `disabled_tools` in `mcp.json`.
- Both stdio and HTTP/SSE MCP transports are wired through (Phase 12). HTTP/SSE servers authenticate via OAuth 2.1 PKCE with token storage at `~/.athena/mcp_tokens.json`. If extending transport behavior, keep both paths covered.

## Slash commands worth knowing about

The full list is in `athena/__main__.py:SLASH_HELP`. The ones likely to come up when reasoning about behavior: `/dump` (print the live system prompt — useful when debugging what the model actually sees), `/cwd` (rebuilds the system prompt in place, preserving history), `/cost` (token counters), `/mcp logs NAME` (stderr tail of a misbehaving MCP server).

## Don't

- Don't loosen the air-gapped-by-default posture documented in the README — HTTP/SSE MCP servers are off unless the user adds them to `mcp.json`, and the OAuth token store is gitignored.
- Don't add prompt-engineered "fake" function calls; everything goes through Ollama's native tool-call protocol.
- Don't add new top-level subdirectories under `athena/` without updating both `ATHENA.md` and this file's architecture section.
- Don't write directly to the SQLite session index — append to JSONL and let the mirror update.
