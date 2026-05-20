# Error handling

athena classifies every API error into one of five recovery actions
and retries automatically where the classification permits.

## Recovery actions

| Action               | Trigger                                   | Behaviour                                                         |
|----------------------|-------------------------------------------|-------------------------------------------------------------------|
| `retry`              | network errors, 5xx, 408, 429             | exponential backoff with jitter, capped at `max_backoff_seconds`  |
| `rotate_credential`  | repeated 429 on one key with a pool       | switch to next non-cooldown credential; abort if none             |
| `compress_context`   | "prompt is too long" / context-length     | call the registered compressor; retry once (T2-04 wires)          |
| `abort`              | 4xx other than 408/429, unknown error     | surface the original exception to the caller                      |
| `fallback_provider`  | (reserved — Tier 3/4)                     | treated as `abort` until cross-provider fallback ships            |

Classification priority order (first match wins):

1. `httpx.ConnectError` / `ConnectTimeout` → `NETWORK` + `retry`
2. `httpx.ReadTimeout` / `WriteTimeout` / `PoolTimeout` → `TIMEOUT` + `retry`
3. HTTP status (from `response_status` or `HTTPStatusError`):
   - `429` → `RATE_LIMIT` + `retry` (Retry-After populates `suggested_backoff_s`)
   - `408` → `TIMEOUT` + `retry`
   - `5xx` → `SERVER_5XX` + `retry` (or `COMPRESS_CONTEXT` if the body matches)
   - `400` with a context-length message → `COMPRESS_CONTEXT`
   - `4xx` other → `CLIENT_4XX` + `abort`
4. `httpx.ReadError` / "stream" in the message → `STREAM` + `retry`
5. `httpx.RemoteProtocolError` / generic `NetworkError` → `NETWORK` + `retry`
6. `ValueError` with "json" in the message → `PARSE` + `retry`
7. Bare exception text matching a context-length pattern → `COMPRESS_CONTEXT`
8. Default → `UNKNOWN` + `abort`

The patterns matching context-length errors cover Anthropic
(`prompt is too long`), OpenAI (`maximum context length`, `context
length ... exceeded`), Gemini (`exceeds the maximum input token
count`), and Ollama (`too many tokens`, generic `input length ...
exceeds`).

## Retry budget

- Per call: `max_retries_per_turn` (default `5`).
- Per retry: exponential backoff `2^attempt + uniform(0, 1)` seconds,
  capped at `max_backoff_seconds` (default `30.0`).
- A server-supplied `Retry-After` header overrides the exponential
  formula but is *also* capped at `max_backoff_seconds`, so a stray
  `Retry-After: 600` can't accidentally pause the agent for ten
  minutes.

The budget counts every recovery attempt regardless of action.
Exceeding the budget raises `RetryBudgetExceeded`, carrying the last
classification so callers can inspect what eventually exhausted it.

## Configuration

```toml
max_retries_per_turn = 5
max_backoff_seconds = 30.0
```

## Observing retries

`/status` (slash) or `athena status` (CLI subcommand) renders:

```
retries this session:
  anthropic: 2 retries, 0 aborts
```

The counter is per-provider, lifetime of the provider instance (one
agent session). Providers without retry instrumentation (Google,
custom backends) are omitted from the section; if every provider in
use lacks the accessor the section is omitted entirely.

## Interrupts

`KeyboardInterrupt` and `SystemExit` propagate through `with_retry`
immediately — never classified, never retried. `asyncio.CancelledError`
is an `Exception` (3.8+); it falls through the classifier as
`UNKNOWN` → `abort`, which also re-raises immediately. Net effect:
all three interrupt mechanisms reach the caller in O(1) without
sleeping or counting against the retry budget.

## Implementation

- `athena/providers/error_classifier.py` — pure function module.
  `classify(exc, *, response_status, response_text, retry_after_header)
  -> Classification`. Patterns are easy to extend; add a new regex to
  `_CONTEXT_LENGTH_PATTERNS` if a provider surfaces a novel
  context-length message.
- `athena/providers/retry_utils.py` — `with_retry(operation, ...)`
  executes the recovery loop. Sync (matches the sync provider
  surface); a future async-provider phase would add
  `with_retry_async` next to it.
- `athena/providers/credential_pool.py:rotate_to_next(provider_name)
  -> Credential | None` — pool's contribution to the
  `on_rotate_credential` callback.
- Per-provider integration: each provider's `stream_chat` wraps
  open-stream + raise-for-status + rate-limit-capture in
  `with_retry`. The streaming body itself is *outside* the retry
  boundary because yielded chunks can't be replayed.
