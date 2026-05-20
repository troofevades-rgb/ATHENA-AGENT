# Claude Desktop + athena MCP integration runbook

Manual smoke test for `athena mcp serve`. Run when you have Claude
Desktop installed and want to verify the wedge — Claude calling
athena's curated tools as a peer in the MCP graph.

## Prereqs

- Claude Desktop installed.
- `athena-coder` installed and on PATH (`which athena` should
  resolve).

## Configure Claude Desktop

Edit Claude Desktop's MCP config file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

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

If `athena` isn't globally on PATH (e.g. you installed via
`pipx install` which puts it in `~/.local/bin` or the pipx venv),
use the absolute path Claude Desktop will spawn:

```bash
which athena   # macOS/Linux
where athena   # Windows
```

Then use that absolute path as `command`.

Restart Claude Desktop.

## Verify

1. **Tools appear.** Open the tool picker; you should see seven
   tools prefixed `athena_*`. No error toast about athena failing
   to start.

2. **list_skills.** Ask: *"Using the athena MCP, list available
   skills."* Verify the response includes the skills under your
   `.athena/skills/` directory (or a clean "no skills" message
   if you have none).

3. **snapshot_files.** Ask: *"Snapshot `/tmp/test.txt` using
   athena."* (Create the file first if it doesn't exist.) Verify a
   `snapshot_id` is returned. Check `~/.athena/snapshots/` for a
   new tarball + sidecar.

4. **rollback_files.** Modify `/tmp/test.txt`. Ask Claude to
   rollback using the snapshot_id from step 3. Verify the file is
   restored.

5. **audit_query.** Ask: *"Show athena's audit log for the last
   month."* Verify entries return (or "no audit records" on a
   fresh install).

## Record what you ran

Save the session as `docs/proof/mcp-claude-desktop-session.md`:

```markdown
# Claude Desktop + athena MCP — <date>

Did: registered athena under mcpServers, restarted Desktop, ran 5
tool tests.
Got: <one sentence per tool covering result and any quirks>.

## Tool transcripts
<screenshots or copy-pasted exchanges>

## Outcome
✅ Claude Desktop can call athena MCP tools end-to-end.
```

## When it fails

- **Server doesn't start:** Claude Desktop logs the spawn output;
  on macOS it's `~/Library/Logs/Claude/mcp-server-athena.log`,
  on Windows `%APPDATA%\Claude\logs\`. Check for a missing
  dependency or a wrong path to `athena`.
- **Tools don't appear:** verify the JSON config is valid (e.g.
  `jq . claude_desktop_config.json`). Restart Desktop fully.
- **A tool errors:** Run the same operation via athena's CLI to
  isolate whether the bug is in athena's tool logic or the MCP
  bridge. The 35 unit tests in `tests/mcp/` should already cover
  the bridge; report a regression if they pass but Desktop fails.

## Notes

The 35-test suite in `tests/mcp/` already validates the JSON-RPC
boundary (handshake, dispatch, all 7 tools, all 6 stdio scenarios)
hermetically. This runbook is the wedge-validating integration test
— proof that a real MCP client can talk to athena and use its
tools meaningfully.
