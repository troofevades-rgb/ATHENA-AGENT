# athena proxy

`athena proxy` runs a local OpenAI-compatible HTTP endpoint backed by
athena's full provider stack — prompt caching, retry, rate-limit
tracking, error classification. Any third-party tool that speaks
OpenAI Chat Completions can use athena as its backend.

## Install

The proxy is an optional extra; FastAPI and uvicorn aren't pulled
into headless installs.

```bash
pipx install --force "athena-coder[proxy]"
```

## Quick start

```bash
# Terminal 1
athena proxy

# Terminal 2 — point any OpenAI-compatible tool at the proxy
aider \
  --openai-api-base http://localhost:11434/v1 \
  --openai-api-key dummy \
  --model claude-sonnet-4-6
```

The default port is `11434` — Ollama's default. The proxy slots in
cleanly when Ollama isn't running and any tool already configured
for Ollama works against athena unchanged.

## How requests get routed

1. `X-Athena-Provider: <name>` header (if present and the named
   provider has credentials).
2. Model-name match — `claude-*` → anthropic, `gpt-*` → openai,
   `gemini-*` → google.
3. Fall back to `cfg.proxy_default_provider`.

Returns `400` if nothing claims the request and the default isn't
available.

## Endpoints

| Method | Path | Notes |
|--------|------|-------|
| GET    | /v1/models | Union of every available provider's catalog |
| POST   | /v1/chat/completions | OpenAI Chat Completions, streaming + non-streaming |
| POST   | /v1/embeddings | 501 — not implemented |

## Configuration

```toml
proxy_default_provider = "anthropic"
proxy_bind_host = "127.0.0.1"
proxy_bind_port = 11434
proxy_log_path = "~/.athena/proxy.jsonl"
proxy_log_bodies = false
proxy_bodies_dir = "~/.athena/proxy_bodies"
```

CLI flags override config: `--host`, `--port`, `--provider`,
`--log-bodies`, `--no-translate`. `--bind-public` is the only way
to bind `0.0.0.0` (defense-in-depth: the proxy forwards using
your API keys).

## What gets logged

One JSONL line per request lands in `~/.athena/proxy.jsonl`:

```json
{
  "request_id": "chatcmpl-...",
  "ts": "2026-05-19T...",
  "client_ua": "Aider/0.51.0",
  "model_requested": "claude-sonnet-4-6",
  "provider_used": "anthropic",
  "latency_ms": 1234.5,
  "tokens_in": 1500,
  "tokens_out": 320,
  "cache_read_tokens": 1280,
  "request_summary": {"message_count": 4, "has_tools": true, "stream": true},
  "response_summary": {"finish_reason": "tool_calls", "has_tool_calls": true}
}
```

With `--log-bodies` (or `proxy_log_bodies = true`), the full
request and response payloads land at
`~/.athena/proxy_bodies/<request_id>.json`. Useful for debugging
translation issues; bodies can exceed 50 KB so they're opt-in.

## Translation

The translator at `athena/proxy/translator.py` covers the
OpenAI ↔ Anthropic differences:

- system message extraction (OpenAI inline role → Anthropic top-level)
- tools schema unwrap (`{type:function, function:{...}}` →
  `{name, description, input_schema}`)
- tool_choice mapping (`auto`/`required`/`none`/`{type:function}` →
  `auto`/`any`/`none`/`tool`)
- `role="tool"` messages folding into `role="user"` content blocks
  with `tool_result` entries
- stop sequences, max_tokens, temperature, top_p passthrough

The default server path routes through `provider.stream_chat` and
keeps the existing caching/retry/rate-limit machinery — request
translation happens inside `AnthropicProvider`, not at the proxy
layer, so the dedicated `openai_request_to_anthropic` helper is
held in reserve for a future `--no-translate` deep-integration mode.

## Limitations

- Embeddings endpoint stubbed (501).
- Reasoning tokens (o1/o3 style, Anthropic extended thinking) pass
  through where shapes align and drop otherwise.
- No proxy-side context compression — the proxy is stateless per
  request.
- No persistent session state across requests.

## Security

127.0.0.1 by default. `--bind-public` is required to bind 0.0.0.0
and prints a warning when used. Bearer auth is reserved
(`proxy_require_auth`) but not wired in this release; the localhost
socket is the security boundary.

## Smoke testing

Two runbooks in `docs/proof/` walk through manual integration tests:

- `proxy-aider-runbook.md` — Aider, the canonical client
- `proxy-clients-runbook.md` — Cline, Codex CLI, Continue, OpenAI SDK
