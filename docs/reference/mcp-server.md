# athena MCP server

`athena mcp serve` runs an MCP (Model Context Protocol) server
exposing athena's read-only and snapshot-revert tool surface to any
MCP-capable client — Claude Desktop, Claude Code, Cursor, anything
that speaks the spec.

This makes athena a **peer** in a multi-agent graph: a Claude
Desktop user can say *"use athena to roll back the last skill
mutation"* and Desktop's agent will call athena's tool over MCP and
surface the result. Athena becomes a citation in other agents'
trajectories, not just the operator behind them.

## Quick start with Claude Desktop

Edit Desktop's config (macOS path; see runbook for Windows/Linux):

```json
{
  "mcpServers": {
    "athena": {
      "command": "athena",
      "args": ["mcp", "serve"]
    }
  }
}
```

Restart Desktop. The seven `athena_*` tools appear in the tool
picker.

## Tools exposed

| Tool | Purpose |
|------|---------|
| `athena_snapshot_files` | Capture a content-addressed snapshot of one or more files |
| `athena_rollback_files` | Restore files from a prior snapshot |
| `athena_list_skills` | List skill catalogue (name, description, state, pinned) |
| `athena_read_skill` | Read the full body of one skill |
| `athena_list_memories` | List memory entries for a profile |
| `athena_read_memory` | Read one memory entry's body |
| `athena_audit_query` | Query the mutation audit log (since/until/tool_name/write_origin filters) |

No `bash`, no `Write`, no arbitrary code execution. Curated by
design — exposing athena's broader tool surface over MCP would
turn the server into a code-execution gateway for any MCP client.

## Resources exposed

| URI | Content |
|-----|---------|
| `athena://skills/` | Skill catalogue index (markdown) |
| `athena://skills/<name>` | One skill body |
| `athena://memories/` | Memory index for the active profile |
| `athena://memories/<name>` | One memory entry |
| `athena://audit/` | List of available audit months |
| `athena://audit/<YYYY-MM>` | One month's audit JSONL |

## Transports

- **stdio** (default; spec-canonical) — the MCP client launches
  `athena mcp serve` as a subprocess and pipes JSON-RPC over
  stdin/stdout. Used by Claude Desktop and most MCP clients.
- **sse** — reserved for a follow-up release; CLI returns a 2 with
  a hint if requested today.

## Configuration

```toml
mcp_default_transport = "stdio"
mcp_sse_port = 8765
mcp_log_path = "~/.athena/mcp.jsonl"
mcp_allow_write = false   # reserved; no write tools advertised yet
```

CLI flags on `athena mcp serve`:

- `--transport {stdio,sse}` — overrides `cfg.mcp_default_transport`.
- `--workspace PATH` — workspace for skill discovery (default: cwd).
- `--profile NAME` — memory profile (default: `cfg.profile`).
- `--audit-dir PATH` — audit log dir (default: `~/.athena/audit`).
- `--allow-write` — reserved.

## What the server advertises

- Protocol version `2024-11-05` (pinned; bump when the MCP spec
  revs).
- Capabilities: `tools` + `resources` only. **No** `prompts`,
  **no** `sampling` — fake capabilities cause clients to call
  methods we don't implement.
- `serverInfo.version` carries athena's `__version__`.

## Smoke testing

The 35-test suite in `tests/mcp/` covers the boundary hermetically:

- `tests/mcp/test_handshake.py` — initialize / capabilities /
  dispatch / errors
- `tests/mcp/test_tools.py` — all 7 tools, happy + error paths
- `tests/mcp/test_stdio_transport.py` — full roundtrip via
  `io.StringIO` substitution

A runbook for the real-client integration test against Claude
Desktop lives at
`tests/mcp/test_integration_with_claude_desktop.md`.

## Logging

All logs go to **stderr** because stdout is the JSON-RPC wire —
printing logs to stdout corrupts the stream. Run with
`PYTHONLOGGINGLEVEL=DEBUG` to crank up verbosity when diagnosing
client issues.

## Security

- No arbitrary code execution exposed.
- Default surface is read + revert; the only mutation is rollback,
  which restores from a sanctioned snapshot.
- Stdio trust is implicit (the parent process launched us).
- `--allow-write` is reserved for a future opt-in to write-capable
  tools; nothing ships under it today.
