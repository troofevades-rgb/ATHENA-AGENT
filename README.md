# ocode — local Claude Code alternative on Ollama

A terminal-based agentic coding assistant that runs entirely against a local Ollama server. No cloud calls, no API keys, no telemetry. Designed for offline / air-gapped use.

## Features

- Native Ollama tool calling (no prompt-engineered fake function calls)
- Streaming token output
- File read / write / surgical edit via `str_replace`
- Bash execution with per-call confirmation for destructive ops; works on Linux, macOS, and Windows (git-bash auto-detected)
- Glob + ripgrep-style search
- Project context loaded from `OCODE.md` (analogous to `CLAUDE.md`)
- Slash commands: `/clear`, `/cost`, `/model`, `/tools`, `/help`, `/exit`, `/dump`, `/cwd`, `/loop`, `/compact`, `/resume`, `/memory`, `/plan`, `/review`, `/security-review`, `/init`, `/steer`, `/queue`, `/goal`
- Session transcript saved to `~/.ocode/profiles/<profile>/sessions/` with SQLite FTS5 search
- Sub-agent forks via `Agent.fork()` (daemon-thread; isolated provider client; auto-deny approval callback)
- File-based skill system (agentskills.io standard), plus `import-from-hermes`
- Per-turn background review and 7-day curator pass — autonomous memory/skill consolidation
- Plugin system with lifecycle hooks (`ocode plugins list|enable|disable|info`)
- APScheduler-backed cron with watchdog and agent modes (`ocode cron ...`)
- In-flight redirection (`/steer`) and persistent invariant (`/goal`)
- Closed training loop: review trajectories, build SFT+DPO datasets, train a new LoRA, register with Ollama (`ocode train review|build-dataset|run|status`, `ocode model switch`)
- Rich terminal UI with diff rendering for edits

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) running locally (default `http://127.0.0.1:11434`)
- A tool-capable model. Recommended for a 4070 Ti Super (16GB):
  - `qwen2.5-coder:14b` — best balance of speed and capability (default)
  - `qwen2.5-coder:32b` — better reasoning, will spill to RAM, slower
  - `llama3.1:8b` — fast fallback
  - `qwen3:14b` — newer, also good
- Optional: `ripgrep` (`rg`) on PATH for faster search; falls back to Python.

## Install

```bash
cd ocode
pip install -e .
ollama pull qwen2.5-coder:14b
```

## Run

```bash
ocode                       # interactive REPL in current directory
ocode -m qwen2.5-coder:32b  # pick a different model
ocode -p "fix the failing test in test_parser.py"   # one-shot prompt
```

## Configuration

`~/.ocode/config.toml`:

```toml
model = "qwen2.5-coder:14b"
ollama_host = "http://127.0.0.1:11434"
auto_approve_bash = false   # if true, no confirmation prompts for bash
context_window = 32768
```

## Project memory

Drop an `OCODE.md` at the repo root. It gets prepended to the system prompt every session — same idea as `CLAUDE.md`. Keep it terse: build commands, conventions, gotchas.

## Architecture

```
agent loop  ->  ollama (tool-call request)
    ^                   |
    |                   v
    +---  tool exec  <--+
```

Single loop in `agent.py`. Tools are registered in `tools/registry.py` with a JSON schema Ollama understands; new tools just need a `@tool(...)` decorator and a Python function.

## Extending

Add a tool in `ocode/tools/`:

```python
from .registry import tool

@tool(
    name="git_status",
    description="Run git status in the working directory",
    parameters={"type": "object", "properties": {}},
)
def git_status() -> str:
    import subprocess
    return subprocess.check_output(["git", "status"], text=True)
```

Import it in `tools/__init__.py` and it's live next session.

## MCP integration

ocode reads `mcp.json` files in the standard Claude Desktop / Claude Code format and registers each server's tools alongside the built-in ones. Lookup order (later overrides earlier):

1. `~/.ocode/mcp.json`
2. `<workspace>/.ocode/mcp.json`
3. `<workspace>/mcp.json`

Example:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/matt/work"]
    },
    "git": {
      "command": "uvx",
      "args": ["mcp-server-git", "--repository", "."]
    }
  }
}
```

Per-server config supports the standard fields (`command`, `args`, `env`, `cwd`, `disabled`) plus two ocode extensions for trimming what the model sees:

- `allowed_tools`: whitelist of tool names to expose
- `disabled_tools`: blacklist of tool names to hide

Tools land in the registry namespaced as `{server}__{tool}` (e.g. `git__git_status`). The model sees them indistinguishably from built-ins. Use `/mcp` to see what's connected, `/mcp logs <name>` to inspect a server's stderr if it's misbehaving.

Only the **stdio** transport is supported. HTTP/SSE servers are skipped with a warning. For air-gapped use this is fine — every common MCP server (filesystem, git, sqlite, postgres, github offline, etc.) ships as a stdio subprocess.

### Writing your own MCP server

`ocode/mcp/demo_server.py` is a complete ~120-line stdlib-only MCP server. Copy it as a starting point — it exposes `echo`, `add`, and `current_time`, and is the test fixture that proves the integration works without external dependencies.

### Limitations

- No HTTP/SSE transport. (Hooks are in place in `mcp/client.py`; the loader checks for `url` and skips with a warning.)
- No prompts or resources. Only `tools/list` + `tools/call` are wired through. Prompts/resources are valid follow-ons; the JSON-RPC plumbing already handles them.
- No sampling. If a server requests model completions from us, we reply with method-not-found. Most servers don't need this.
- Per-tool confirmation prompts only fire for built-in tools that opt in. MCP-bridged tools always run without confirmation; if you want a destructive MCP tool gated, add it to `disabled_tools` in your `mcp.json`.

## Other limitations

- Local models are weaker at long-horizon planning than Claude. Keep tasks scoped.
- No sub-agent / parallel tool execution.
- Diff rendering is line-based, not semantic.
