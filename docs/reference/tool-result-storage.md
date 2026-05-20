# Out-of-band tool result storage

Tool outputs exceeding `tool_result_threshold_bytes` (default 1MB)
are persisted out of band as content-addressed blobs under
`~/.athena/tool_results/`. The agent sees a short reference handle
in conversation history rather than the raw text; if it needs to
read the stored content, it calls the `read_tool_result` tool with
the handle.

## How it works

1. Tool dispatch produces a stringified result via
   `athena/tools/registry.py:dispatch`.
2. `Agent._maybe_store_tool_result` checks the result size against
   `cfg.tool_result_threshold_bytes`.
3. Over-threshold content goes through
   `ToolResultStorage.store(content, *, tool_name)`:
   - SHA-256 first 16 hex chars → blob filename
   - Atomic `secure_write_text` at mode `0o600` (T1-06)
   - One-line JSONL append to the index
4. The agent receives the handle:
   ```
   [tool_result:abc123def456789a — 47.3MB output stored. Use read_tool_result to access.]
   ```
5. PostToolUse hooks + plugins still see the **raw** result; only
   the version that lands in `agent.messages` / session JSONL is
   the handle.

## Reading stored results

Use the `read_tool_result` tool:

```
read_tool_result(handle="abc123def456789a", max_bytes=100000, offset=0)
```

Or with the bracketed handle verbatim:

```
read_tool_result(handle="[tool_result:abc123def456789a — 47.3MB ...]")
```

Pagination via `offset` + `max_bytes` lets the agent stream through
a large blob without re-inlining the whole thing.

## Cleanup

Blobs accumulate over time. Run:

```
athena cleanup-blobs --older-than 30
athena cleanup-blobs --older-than 30 --dry-run
```

The sweeper walks every `profiles/<name>/sessions/*.jsonl` under
`~/.athena/`, extracts every handle/bare-hash reference, then
deletes blobs that are:
1. Not referenced by any session log, AND
2. Older than `--older-than` days (default 30).

Recent blobs are always kept regardless of reference state — so a
freshly-stored blob can't be GC'd before the session that produced
it ever gets a chance to write itself down.

Suggested cron entry:

```cron
0 3 * * * athena cleanup-blobs --older-than 30
```

The slash command syntax differs from the spec (`athena tools
cleanup-blobs`) because athena's CLI uses flat subcommands; the
nested `tools` group doesn't exist. Functionally equivalent.

## Configuration

```toml
tool_result_threshold_bytes = 1_000_000
tool_result_storage_path = "~/.athena/tool_results"
```

Lowering the threshold (e.g. to `100_000`) catches more outputs;
raising it (`10_000_000`) is appropriate when working with large
trusted models that emit big tool calls deliberately.

## Implementation

- `athena/tools/tool_result_storage.py` — `ToolResultStorage` class
  + `maybe_store_result` dispatch helper + `HANDLE_RE` regex.
- `athena/tools/read_tool_result.py` — the `read_tool_result` tool
  registered via `@tool(...)`. Resolves the active agent via
  `get_current_agent()`.
- `athena/agent/core.py:Agent._maybe_store_tool_result` — the
  dispatch-side hook called from `_handle_tool_call` after the tool
  runs but before the result is recorded into history.
- `athena/cli/cleanup_blobs.py` — `athena cleanup-blobs` CLI
  subcommand.

## Notes on limitations

- **Idempotent by content hash.** Two tools that return identical
  content share a single blob. Index entries differentiate the
  tools/sessions; the blob itself doesn't.
- **Binary outputs** (images, archives) are not currently supported
  — every blob is stored as UTF-8 text. A future phase can extend
  the index with a `content_type` field.
- **Cleanup is opt-in cron, not always-on.** Athena doesn't
  auto-GC; storage grows until the user runs `cleanup-blobs`.
- **No multi-process locking.** Content-addressed storage means
  concurrent writes of the same content are idempotent; concurrent
  writes of different content land in different files; index
  appends use O_APPEND for atomicity on POSIX.
