# Project: ocode

## Stack
- Python 3.10+, httpx, rich, prompt_toolkit, pyyaml
- Talks to local Ollama at $OLLAMA_HOST (default http://localhost:11434)

## Build/test
- `pip install -e .` (already done in .venv)
- `pytest tests/ -q`
- `pytest tests/ --cov=ocode.skills --cov=ocode.migration -q` for coverage

## Layout
- ocode/agent/           agent subpackage
  - core.py              `Agent` class and the main run-turn loop
  - fork.py              `Agent.fork()` — daemon-thread sub-agents (used by
                         the `Agent` tool, background review, and the curator)
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
                         /plan, /init, /memory, /review). Renamed from
                         ocode/skills/ in Phase 1.
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
- ocode/cli/             non-REPL subcommands (import-from-hermes)
- ocode/ollama_client.py thin /api/chat wrapper
- ocode/tools/           built-in model tools
  - registry.py          toolset-scoped registry; tools declare a `toolset`
                         and optional `check_fn` for capability-based gating
  - skill_tools.py       skills_list, skill_view, skill_manage (toolset=skills)
  - recall_tools.py      search_sessions (toolset=recall)
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

## CLI
- `ocode` — interactive REPL (default)
- `ocode -p "<prompt>"` — one-shot prompt
- `ocode import-from-hermes --source PATH --dest PATH [--dry-run]` —
  migrate a Hermes home into ocode v2
- `ocode sessions {list,browse,search,purge}` — inspect prior sessions
- `ocode reindex [--profile NAME]` — rebuild the session FTS5 index from JSONL
