# Project: ocode

## Stack
- Python 3.10+, httpx, rich, prompt_toolkit
- Talks to local Ollama at $OLLAMA_HOST (default http://localhost:11434)

## Build/test
- `pip install -e .` (already done in .venv)
- `pytest tests/ -q`

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
- ocode/ollama_client.py thin /api/chat wrapper
- ocode/tools/           built-in tools (Read/Write/Edit/Bash/Glob/Grep/Agent/…)
  - registry.py          toolset-scoped registry; tools declare a `toolset` and
                         optional `check_fn` for capability-based advertisement
  - agent_tool.py        sub-agent dispatch (thin wrapper around `Agent.fork()`)
- ocode/mcp/             MCP stdio integration

## Conventions
- New built-in tools register via `@tool(name=…, toolset=…, …)` in `ocode/tools/`
- Toolsets group tools by capability surface. `enabled_toolsets` scopes which
  tools the model sees; forks always pass an explicit list.
- Keep tool descriptions terse but include hints about preferred use
