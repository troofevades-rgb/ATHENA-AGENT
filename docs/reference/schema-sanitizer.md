# Tool-call argument sanitizer

Local models (Qwen, Llama, Mistral, DeepSeek) emit malformed JSON
in tool-call argument fields at rates of 5–15% depending on model
and prompt shape. Hosted models do this occasionally too — usually
a trailing comma or smart-quote artifact in the streaming output.

athena's sanitizer attempts a sequence of forgiving passes to
recover the intended JSON before tool dispatch.

## Pass order

First successful parse wins:

1. **Direct** `json.loads`. Already-valid JSON skips the rest.
2. **Smart quotes** (`'`, `'`, `"`, `"`, `′`, `″`) → ASCII quotes.
3. **Single-quoted strings** (`'foo'`) → double-quoted (`"foo"`),
   but only when the payload has no double-quoted strings already
   (avoids breaking `"Mike's file"`-style apostrophes inside
   double-quoted strings).
4. **Trailing commas** (`,}` and `,]`) removed.
5. **Unquoted top-level keys** (`{key:` or `, key:`) → quoted.
   Nested unquoted keys mid-value are intentionally NOT touched —
   too ambiguous to rewrite safely.
6. **Optional `demjson3` fallback** if the user has `demjson3`
   installed in their environment. Not a hard dependency.

## What the sanitizer refuses to do

- **Never modifies the tool name.** The function signature accepts
  the tool name only for logging. If a model emits a misspelled
  tool name, the agent surfaces "unknown tool" rather than the
  sanitizer guessing.
- **Refuses semantic guesses.** Missing values, extra values, or
  ambiguous nesting return `None`. Better to surface the error
  than to dispatch a tool with wrong args.
- **Pure function.** No I/O, no exceptions raised — every parse
  failure caught internally. Idempotent on already-valid JSON.

## Configuration

```toml
tool_call_sanitize = true
```

`tool_call_sanitize = false` disables the sanitizer entirely; tool
dispatch falls back to raw `json.loads`. Useful for debugging
upstream model behaviour without the sanitizer's regex rescue
masking the raw payload.

## What you'll see in the log

When a fix applies, the REPL surfaces:

```
sanitised tool-call args for Read: trailing commas removed, unquoted keys quoted
```

When sanitization can't recover, the logger emits a `WARNING` with
the truncated (500-char) payload + list of attempted fixes so a
post-incident grep finds the case.

## Implementation

- `athena/providers/schema_sanitizer.py` — pure module exporting
  `sanitize_tool_call_args(raw, *, tool_name) -> (sanitized_or_none,
  fixes_applied)`.
- `athena/agent/core.py:Agent._handle_tool_call` — the integration
  point. Routes string-shaped tool arguments through the sanitizer
  before `json.loads` when `cfg.tool_call_sanitize` is True.

## Notes on limitations

- **Nested unquoted keys are not handled.** Only keys at object
  boundaries (`{` or `,`) get quoted. Nested unquoted keys mid-value
  are too ambiguous.
- **JavaScript-style comments** (`//`, `/* */`) are not handled.
  Add a `_strip_comments` pass if real-world data shows it.
- **Hex numbers (`0xFF`)** are not handled. JSON doesn't support
  them; LLMs almost never emit them in tool args.
