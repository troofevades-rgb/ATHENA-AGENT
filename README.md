<div align="center">

<pre>
⢀⣀⣠⣶⣾⣿⣷⣦⣄⣀
⠀⣽⠟⡻⢿⣿⡿⢛⠻⣿
⢰⣷⣙⣋⣼⢻⣇⣛⣡⣿⡆
⠈⣿⣿⣿⣿⣶⣿⣿⣿⣿⣧
⢰⣿⣿⣿⣻⣿⣿⣿⣿⣿⣿⣷⡀
⠘⣿⣿⣿⡹⣿⣿⣿⣿⣿⣿⣿⣿⣄
⠀⢹⣿⣿⣷⣬⡛⢿⣿⣿⣿⣿⣿⣿⡆
⠀⠀⠙⣿⣿⣿⣿⣷⣮⣝⣻⢿⣿⣿⣿⡄
⠀⠀⠀⠀⠙⢿⣿⣿⣿⣿⣿⣿⣿⣿⠿⣷
⠀⠀⠀⠀⠀⠀⠈⣿⣿⡏⠉⠉⠉⠋
</pre>

# Athena
*Wisdom in your terminal.*

**A local-first, terminal-native agentic coding assistant.**


Run on your own Ollama models by default, hosted providers when you want them.

[![tests](https://github.com/troofevades-rgb/ATHENA-AGENT/actions/workflows/tests.yml/badge.svg?branch=master)](https://github.com/troofevades-rgb/ATHENA-AGENT/actions/workflows/tests.yml)
[![coverage](https://github.com/troofevades-rgb/ATHENA-AGENT/actions/workflows/coverage.yml/badge.svg?branch=master)](https://github.com/troofevades-rgb/ATHENA-AGENT/actions/workflows/coverage.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

</div>

---

athena gives you a full agentic coding loop in your terminal — native tool calling, file edits, shell, search, plan mode — **without sending your code anywhere**. It talks to a local [Ollama](https://ollama.com) daemon by default; point it at a hosted model only when you choose to.

> **Status — Beta.** The default Ollama path is production-ready for single-user development on Linux/macOS. Hosted providers, the multi-user gateway, and the GPU training loop are functional and actively hardening.

## Highlights

- **Runs on your models.** Ollama by default; Anthropic, OpenAI, Google, OpenRouter, and Nous Portal through one credential pool with automatic key rotation on 429.
- **A real coding agent.** Native tool calls (no prompt-engineered fakes), surgical file edits, gated Bash, ripgrep search, plan mode, in-flight `/steer`, and a persistent `/goal` invariant.
- **Tuned for small / local models.** Recovers when the model narrates instead of acting, repairs malformed tool calls, breaks stuck loops, and (opt-in) escalates only the hard moments to a stronger model.
- **MCP client.** stdio **and** HTTP/SSE (OAuth 2.1 PKCE) — any MCP server's tools sit alongside the built-ins.
- **Multimodal.** Vision, OCR, video analysis + generation, audio, document parsing, browser automation (Playwright), and computer-use.
- **Autonomy & memory.** Sub-agent forks, per-turn background review, a 7-day curator pass, file-based skills, and semantic recall across sessions.
- **Connects everywhere.** Messaging gateways (Discord, Slack, Telegram, Signal, Matrix, iMessage, email), cron, webhooks, ACP, and an OpenAI-compatible proxy.
- **Polished TUI.** Native terminal scrolling, a `⏺ Tool(args)` / `⎿ output` call tree, syntax-highlighted markdown, a live context-window gauge, `Ctrl+O` reasoning toggle, and switchable themes.

## Quickstart

```bash
pip install athena-coder
ollama pull qwen2.5-coder:14b 
athena                                # interactive REPL in the current directory
```

```bash
athena -p "fix the failing test in test_parser.py"   # one-shot prompt
athena doctor                                          # health check (config, creds, ollama, tui)
```

<details>
<summary><b>Install from source (development)</b></summary>

```bash
git clone https://github.com/troofevades-rgb/ATHENA-AGENT.git
cd ATHENA-AGENT
pip install -e ".[dev]"
ollama pull qwen2.5-coder:14b
```

The installed CLI is `athena`. Verify with `athena --version`.

</details>

## Requirements

- **Python 3.10+**
- **[Ollama](https://ollama.com)** running locally (default `http://127.0.0.1:11434`) with a tool-capable model:
  - `qwen2.5-coder:14b` — best balance of speed and capability (default)
  - `qwen2.5-coder:32b` — stronger reasoning (spills to RAM, slower)
  - `llama3.1:8b` — fast fallback
- Optional: **`ripgrep`** (`rg`) on `PATH` for faster search; falls back to Python.

## Configuration

`~/.athena/config.toml`:

```toml
model = "qwen2.5-coder:14b"
ollama_host = "http://127.0.0.1:11434"
auto_approve_tools = false   # if true, skip the confirmation prompt for gated tools (Bash, etc.)
context_window = 32768

# Reliability for small / local models
narrate_reprompt_attempts = 1     # re-prompt N times when the model narrates without calling a tool (0 disables)
routing_enabled = false           # opt-in: escalate to a stronger model when the local one gets stuck
routing_escalation_model = ""     # e.g. "anthropic/claude-sonnet-4-5"; required when routing_enabled
recall_auto = false               # opt-in: inject relevant past turns / memory into context each turn
```

## Project memory

Drop an `ATHENA.md` at the repo root — it's prepended to the system prompt every session, same idea as `CLAUDE.md`. Keep it terse: build commands, conventions, gotchas.

## Hosted models

Ollama is the default. To use a hosted provider, add a key to the credential pool, then switch via the picker:

```bash
athena providers add-key openrouter --key sk-or-...
athena providers add-key anthropic  --key sk-ant-...
```

```
/model                            # local Ollama + every hosted model your keys reach
/model 42                         # pick by index
/model anthropic/claude-sonnet-4-5
```

The picker marks OpenRouter models that lack tool calling (`[no-tools]`) — pick a tool-capable model (Claude / GPT-4o / Llama 3.3+) for real work, since athena ships tool schemas every turn.

## Architecture

```
agent loop  ->  provider (tool-call request)
    ^                   |
    |                   v
    +---  tool exec  <--+
```

A single loop in `athena/agent/` (`core.py` plus the `runtime.py` turn-loop mixin). Tools register in `tools/registry.py` with a JSON schema the model understands — a new tool is just a `@tool(...)` decorator on a Python function:

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

<details>
<summary><b>Full feature list</b></summary>

Everything below runs **locally by default** — your own Ollama models, on-disk state, no network egress unless you add a hosted provider or an HTTP MCP server.

**Core coding agent**
- Native tool calling, streaming output
- File read / write / surgical edit (`str_replace`); Bash with per-call confirmation for destructive ops (Linux/macOS/Windows, git-bash auto-detected); Glob + ripgrep search
- Project context auto-loaded from `ATHENA.md`
- Plan mode, in-flight redirects (`/steer`), persistent goal invariant (`/goal`)
- Deep slash-command set: `/model`, `/plan`, `/review`, `/security-review`, `/compact`, `/resume`, `/memory`, `/loop`, `/cost`, `/init`, `/tools`, `/dump`, `/cwd`, `/queue`, …

**Models & providers**
- Ollama (default) plus Anthropic, OpenAI, Google, OpenRouter, Nous Portal — one profile-scoped credential pool, automatic key rotation on 429
- Opt-in struggle-based escalation: stay local, jump to a stronger model only when stuck (`routing_enabled`)

**Reliability for small / local models**
- Re-prompts when the model narrates an action without calling a tool
- Repairs malformed tool calls (suggests the right tool / argument names)
- Circuit breakers for stuck loops and consecutive provider errors
- Semantic recall — past turns + memory embedded into a local vector index and auto-injected (`recall_auto`)

**Multimodal & rich tools**
- Vision (image analysis) and OCR
- Video analysis and generation
- Audio, document parsing, and LSP (language-server) integration
- Browser automation (Playwright) and computer-use (screenshot + control)
- Social search (X/Twitter)

**Autonomy, memory & self-improvement**
- Sub-agent forks (`Agent.fork()`) — isolated daemon-thread agents for parallel work
- Per-turn background review + a 7-day curator pass: autonomous memory / skill consolidation
- File-based skills (agentskills.io standard), memory (per-workspace + global), checkpoints with snapshot-backed rollback
- Closed training loop: review trajectories → SFT+DPO datasets → train a LoRA → register with Ollama → `athena model switch` (GPU)

**Integration & automation**
- MCP client — stdio **and** HTTP/SSE (OAuth 2.1 PKCE)
- Messaging gateways: Discord, Slack, Telegram, Signal, Matrix, iMessage, email
- APScheduler cron (agent + watchdog modes), webhook server, OpenAI-compatible proxy (`athena proxy`)
- ACP (Agent Client Protocol), headless one-shot + batch runs, an eval battery, and a plugin system with lifecycle hooks

**Sessions & safety**
- Session transcripts in `~/.athena/profiles/<profile>/sessions/` with SQLite FTS5 search
- Mutation audit log, approval gating, provenance tracking

**Godmode** (opt-in, `ATHENA_ALLOW_GODMODE=1`)
- Red-teaming / jailbreak toolkit for **your own local models** — system-prompt strategies, prefill injection, multi-model race, and parseltongue obfuscation. Off by default; every invocation warns. See the section below.

</details>

<details>
<summary><b>MCP integration</b></summary>

athena reads `mcp.json` files in the standard Claude Desktop / Claude Code format and registers each server's tools alongside the built-in ones. Lookup order (later overrides earlier):

1. `~/.athena/mcp.json`
2. `<workspace>/.athena/mcp.json`
3. `<workspace>/mcp.json`

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/work"]
    },
    "git": {
      "command": "uvx",
      "args": ["mcp-server-git", "--repository", "."]
    }
  }
}
```

Per-server config supports the standard fields (`command`, `args`, `env`, `cwd`, `disabled`, `startup_timeout`) plus two athena extensions for trimming what the model sees — `allowed_tools` (whitelist) and `disabled_tools` (blacklist). Tools land namespaced as `{server}__{tool}` (e.g. `git__git_status`); the model sees them like built-ins. Use `/mcp` to list connected servers and `/mcp logs <name>` to inspect a misbehaving server's stderr.

**Transports.** Both **stdio** (`command` + `args` + `env`) and **HTTP/SSE** (set `url`; OAuth 2.1 PKCE handled automatically, tokens at `~/.athena/mcp_tokens/<server_id>.json`, mode `0600`). Manage with `athena mcp auth <server>`, `athena mcp token-status`, `athena mcp revoke <server>`. A slow-to-boot server can't brick startup: each connect is bounded by `startup_timeout` (default 10s, overridable per server) and skipped with a warning if it doesn't respond.

**Writing your own.** `athena/mcp/demo_server.py` is a complete ~120-line stdlib-only MCP server (exposes `echo`, `add`, `current_time`) — copy it as a starting point.

**Limitations.** Only `tools/list` + `tools/call` are wired through (no prompts/resources/sampling yet). MCP-bridged tools run without confirmation; gate a destructive one via `disabled_tools`.

</details>

<details>
<summary><b>Godmode — opt-in red-teaming toolkit</b></summary>

`/godmode` is a jailbreaking toolkit for **your own local models** — the intended use is red-teaming a model you deploy and safety research, not coercing a hosted provider's model. It is **off by default**: the command appears in `/help`, but does nothing until you set `ATHENA_ALLOW_GODMODE=1` (in `~/.athena/.env` or the environment), and every invocation while the gate is open prints a one-line warning so you never forget you're inside the opt-in.

Strategies are applied through the existing `/steer` queue (they show up in history as synthetic user messages), with an optional ephemeral system-prompt append and a prefill-messages layer that are never persisted to disk or `/save` transcripts.

```
/godmode list                 list strategies; marks the active one
/godmode apply <strategy>     push a strategy as a steer; mark it active
/godmode clear                push a counter-steer; drop the active marker
/godmode test <query>         preview every strategy's payload for a query
/godmode race <query>         race the query across model tiers
/godmode prefill {set|clear|status}   manage the ephemeral prefill layer
/godmode parseltongue <q>     obfuscate a query (--tier light|standard|heavy)
/godmode save|load <name>     persist / restore a strategy config
```

Related config knobs: `agent_system_prompt_append` (text appended after the `/goal` block) and `agent_prefill_messages_file` (a JSON file of ephemeral prefill messages). The `ATHENA_EPHEMERAL_SYSTEM_PROMPT` env var overrides the append on the fly.

</details>

<details>
<summary><b>Troubleshooting</b></summary>

Start with `athena doctor` — it prints a checklist (config, credentials, ollama, providers, tui) and each `[FAIL]` line tells you what to fix. `athena doctor --no-network` skips remote auth probes; `--json` is machine-readable for CI.

| Symptom | First check |
|---|---|
| Tool calls 400 with "model is not a valid ID" | Run `athena --version`; if old, reinstall to pick up the latest prefix-strip logic |
| Hosted call returns 401/403 | `athena doctor` shows provider auth status |
| REPL "didn't launch" but no error | The Ink TUI almost certainly started — look for the `▸▸` prompt; give the banner 1–2s |
| Crash mid-session | A scrubbed record lands at `~/.athena/crashes/crash-<ts>-<uuid>.json` — attach it to bug reports |

For anything else, paste `athena doctor --json` plus the newest `~/.athena/crashes/*.json`.

</details>

## Limitations

- Local models are weaker at long-horizon planning than frontier hosted models — keep tasks scoped. (`routing_enabled` escalates the stuck moments to a stronger model.)
- Diff rendering is line-based, not semantic.

## License

MIT — see [LICENSE](LICENSE). Change history in [CHANGELOG.md](CHANGELOG.md); release process in [docs/internal/release-process.md](docs/internal/release-process.md).
