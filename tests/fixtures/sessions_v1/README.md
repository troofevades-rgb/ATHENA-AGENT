# `sessions_v1/` — legacy ocode v1 session JSONLs

Session transcripts in the JSONL format used by ocode v1, used by Phase 2
(session store) and Phase 1 (migration) tests. Phase 2's session-store
tests verify that ocode v2's reader handles the legacy shape; the
migration tests verify the importer can re-key v1 sessions into v2's
SQLite index without loss.

## Format

One session per file. Each line is a JSON object — `{"role": "user",
"content": "..."}`, `{"role": "assistant", "content": "...", "tool_calls":
[...]}`, etc. — matching the message shape ocode v1 wrote to disk.

## Layout

```
sessions_v1/
├── trivial.jsonl              # Single user→assistant exchange
├── tool_calls.jsonl           # Session with several tool calls
├── interrupted.jsonl          # Session ending in a Ctrl+C interrupt
├── multi_turn.jsonl           # Long session, many turns
└── malformed_<scenario>.jsonl # Tests of recovery from corruption
```

## Naming

`<descriptive-slug>.jsonl`. Slugs describe what the session exercises —
`tool_calls.jsonl`, not `my-conversation.jsonl`.

## Adding a new sample

1. Anonymize as described under "Provenance" below.
2. Place in this directory (flat — no subdirectories needed).
3. Append a row to the Layout table above.
4. Update the relevant test in `tests/sessions/` or `tests/migration/`.

## Provenance

Samples may come from:

- The user's own `~/.ocode/sessions/` (preferred; anonymize first)
- Hand-crafted JSONL exercising a specific format edge case

**Anonymization rules**:

- Replace user content that names people, projects, or organizations
  with generic placeholders
- Strip any file paths that include `/Users/<name>/` or similar
- Strip any tokens, API keys, or URLs that route to private endpoints
- Tool-call arguments containing paths should be rewritten to
  `/path/to/example`
