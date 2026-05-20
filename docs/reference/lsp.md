# LSP diagnostics

Optional Language Server Protocol surface. When `lsp_enabled = true`,
the agent can call `Diagnose(paths=[...])` and get back a compact
summary of type errors, import errors, and other diagnostics
from whatever language server is configured.

The same function (`athena.tools.diagnose.diagnose_paths`) is the
hook T5-04's verified-execution loop calls as its pre-commit gate.
One implementation, two consumers.

## What it tracks

| Severity | Source field | Renders as |
|----------|--------------|------------|
| Error | `severity: 1` | `[error]` |
| Warning | `severity: 2` | `[warning]` |
| Information | `severity: 3` | `[information]` |
| Hint | `severity: 4` | `[hint]` |

Unknown severities default to Information rather than raising —
unknown servers shouldn't crash the agent.

## Quick start

Install a language server:

```bash
# pyright (recommended)
pip install pyright-langserver
# or
npm install -g pyright

# pylsp (alternative)
pip install python-lsp-server
```

Turn on the gate:

```toml
lsp_enabled = true
# Optional per-language override; the default is
# {"python": ["pyright-langserver", "--stdio"]}
lsp_server_command = {"python" = ["pyright-langserver", "--stdio"]}
lsp_timeout_s = 30.0
```

Then in a session:

```
> Diagnose(paths=["athena/audit/diff.py"])
diagnose: 1 error
  athena/audit/diff.py:42:9 [error] reportUnknownMemberType: Type of "snapshot_id" is partially unknown
```

A clean file:

```
> Diagnose(paths=["athena/audit/diff.py"])
ok (1 file(s) clean)
```

No server installed:

```
> Diagnose(paths=["athena/audit/diff.py"])
ok (no diagnostics — LSP server not installed for python)
```

## Configuration

| Field | Default | Notes |
|-------|---------|-------|
| `lsp_enabled` | `false` | Opt-in. Off → tool reports "LSP disabled" |
| `lsp_server_command` | `{}` | Map `{language: argv}` overriding the built-in default |
| `lsp_timeout_s` | `30.0` | Per-call hard cap; partial diagnostics returned on timeout |

Built-in language map (only Python today; adding more is a
`_DEFAULT_SERVERS` map edit + extension recognition in
`_language_for_path`):

| Language | Default server |
|----------|----------------|
| Python (`.py`) | `pyright-langserver --stdio` |

## Graceful degradation

Every failure mode returns `[]` from the client (and a friendly
"ok" line from the tool) — the agent loop never sees an
exception:

- `lsp_enabled = false` → `[]`
- Path has unmapped language → file silently skipped
- Configured server not on PATH → debug log + `[]`
- Server crashes during initialize → `[]`
- Mid-session exception → caught, `[]`
- Server runs but never publishes diagnostics within
  `lsp_timeout_s` → `[]`

The tool surface distinguishes these cases in the human-readable
output so the operator can see whether the gate is firing or
falling through:

| State | Tool output |
|-------|-------------|
| LSP disabled | `ok (no diagnostics — LSP disabled)` |
| No language mapping | `ok (N file(s); no language mapped)` |
| Server not installed | `ok (no diagnostics — LSP server not installed for X)` |
| Server installed, no issues | `ok (N file(s) clean)` |
| Issues | `diagnose: …` summary lines |

## Wire shape

LSP is JSON-RPC 2.0 over stdin/stdout with `Content-Length: N\r\n\r\n`
message framing. Per-call flow:

1. Spawn the server (`subprocess.Popen(argv, stdin=PIPE, stdout=PIPE)`).
2. Send `initialize` request; await its reply.
3. Send `initialized` notification.
4. For each path: send `textDocument/didOpen` with the file's
   current bytes.
5. Collect `textDocument/publishDiagnostics` notifications until
   every opened path has reported OR `lsp_timeout_s` expires.
6. Send `shutdown` + `exit`.
7. Close the subprocess.

Per call. No persistent server today — the cost is the spawn
latency (typically 500ms–2s for pyright on a warm cache).
Persistent / per-workspace server caching is a future
enhancement.

## T5-04 hookup

`athena.tools.diagnose.diagnose_paths(paths) -> list[Diagnostic]`
is the function the verified-execution loop calls. Same signature
the user-facing tool wraps, same `Diagnostic` dataclass, same
graceful degradation. When T5-04 runs the gate after an edit, a
fresh error-severity diagnostic on a file the agent touched is
the signal that triggers a revert.

## Limitations

- Per-call server spawn (no caching yet).
- Python only (`.py`). Adding TypeScript / Go / Rust is a small
  config + extension-recognition change.
- No `textDocument/codeAction` quick-fix surface; we surface
  diagnostics only.
- No `workspace/configuration` round-trip — the server gets the
  initialize defaults. Project-specific tsconfig / pyrightconfig
  is read by the server itself from disk; athena just opens the
  files.

## Testing

31 tests in `tests/lsp/`:

- `test_client.py` (17) — frame I/O round-trip, end-to-end happy
  path with a `FakeTransport`, empty / disabled / unsupported /
  no-server paths, severity mapping, timeout, transport
  construction failure, session exception, multi-file
  aggregation.
- `test_tool.py` (14) — `format_summary` rendering contract
  (empty / clean / no-server / errors-first / counts /
  pluralisation / truncation), Diagnose wrapper behaviour, the
  diagnose_paths alias T5-04 imports, registry hookup.

Every test runs without spawning a real language server.
