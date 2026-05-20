# T3-01R recon — proxy aiohttp + resolve_provider + observability seams

Goal: rebuild `athena proxy` on the same stack the gateway and
webhook listeners already use (aiohttp + Phase-16 observability),
replacing the original FastAPI implementation. The translation
core stays largely the same; only the HTTP boundary changes.

## (a) aiohttp app/run pattern

Copy `athena/webhooks/server.py`:

- `web.Application()`, `router.add_post(...)`, `router.add_get(...)`.
- Lifecycle is two methods: `async start()` (build `web.AppRunner`,
  `web.TCPSite`, call `await site.start()`) and `async stop()`
  (cancel in-flight tasks, `await runner.cleanup()`).
- Logging goes through `logging.getLogger(__name__).info(...)`.
- Health endpoint `GET /health` returns a JSON status object.

Tests use `aiohttp.test_utils.AioHTTPTestCase` /
`unittest_run_loop`, or the simpler `aiohttp_client` pytest
fixture from `pytest-aiohttp`. The repo doesn't depend on
`pytest-aiohttp` yet, so the cleanest path is to write the tests
with `aiohttp.test_utils.TestServer` + `TestClient` directly —
zero new pytest plugins.

## (b) `resolve_provider` call shape

```python
from athena.providers.runtime_resolver import resolve_provider
from athena.providers.credential_pool import global_pool
from athena.config import load_config

cfg = load_config()
pool = global_pool()        # singleton shared with the agent
provider, bare_model = resolve_provider(model_string, cfg, pool)
chunks = provider.stream_chat(
    model=bare_model,
    messages=messages,
    tools=tools_or_none,
    temperature=temperature_or_default,
    max_tokens=max_tokens_or_none,
)
```

The proxy calls `resolve_provider` per request so the existing
prefix/config/fallback routing applies. `provider.stream_chat`
returns a sync `Iterator[StreamChunk]`; the aiohttp handler runs
it in a threadpool (`asyncio.to_thread`) and yields the SSE bytes
out the response.

## (c) StreamChunk → OpenAI mapping

`athena.providers.base.StreamChunk` has four `kind` values
(constants in `base.py`):

| kind         | payload shape                                  | OpenAI surface                                              |
|--------------|------------------------------------------------|-------------------------------------------------------------|
| `content`    | `str` (token / text fragment)                  | `choices[0].delta.content`                                  |
| `tool_call`  | `{"id", "name", "arguments"}`                  | `choices[0].delta.tool_calls[i].function.{name,arguments}`  |
| `usage`      | `{"prompt_tokens", "completion_tokens", "cache_read_input_tokens"}` | top-level `usage` (final non-streaming) or omitted in SSE  |
| `end`        | `{"reason": "stop"|"length"|"tool_calls"|...}` | `choices[0].finish_reason` (mapped: `end_turn→stop`, etc.)  |

SSE wire format: each chunk is `data: <json>\n\n`; final marker
is `data: [DONE]\n\n`. The non-streaming response collapses the
stream into one `chat.completion` object with `choices[0].message`
holding the joined text + tool_calls list, `finish_reason`, and
`usage`.

This is already implemented in
`athena/proxy/server.py::stream_chunks_to_openai_sse` +
`collect_chunks_to_openai_response`. The retargeting just lifts
those functions into a dedicated `translate.py` module + tests.

## (d) Observability hook

`athena/plugins/bundled/observability/spans.py` exposes a
no-op-safe context manager:

```python
from athena.plugins.bundled.observability.spans import start_span

with start_span(
    "athena.proxy.call",
    {
        "provider": provider_name,
        "model": resolved_model,
        "stream": stream,
        "client_ua": client_ua,
    },
) as span:
    ...
    if span is not None:
        span.set_attribute("usage.prompt_tokens", tokens_in)
        span.set_attribute("usage.completion_tokens", tokens_out)
        span.set_attribute("latency_ms", latency_ms)
```

When the `[observability]` extra is installed the span gets
exported via the configured OTel exporter; without it the
wrapper is inert. Either way the proxy stays functionally
correct.

Redaction: the gateway server logs requests with auth tokens
stripped (`athena/gateway/...`). For the proxy the only secret
in scope is the upstream provider's API key — which never lands
in the request body since clients send a `Bearer dummy`-shape
token that we ignore. Logging is safe.

## Migration plan from the FastAPI version

1. Extract translation from `server.py` into `translate.py`
   (tested in isolation).
2. Rewrite `server.py` on aiohttp matching the webhook pattern.
3. Drop the `[proxy]` extra's FastAPI/uvicorn deps from
   `pyproject.toml` — aiohttp is already pulled by gateway/webhooks.
4. CLI subcommand keeps the same flags; switch from `uvicorn.run`
   to `web.run_app`.
5. Tests rebuilt against `aiohttp.test_utils.TestServer`.

ProxyLogger (`athena/proxy/logging.py`) and the router
(`athena/proxy/router.py`) stay as-is — they're framework-agnostic.
