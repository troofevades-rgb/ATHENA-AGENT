"""End-to-end aiohttp server tests (T3-01R.3).

Uses ``aiohttp.test_utils.TestServer`` + ``TestClient`` so the
suite doesn't need pytest-aiohttp. A stub provider replaces
athena's resolver path; tests stay hermetic (no network, no
credential pool).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from athena.config import Config
from athena.providers.base import Provider, StreamChunk


@dataclass
class StubProvider(Provider):
    name: str = "anthropic"
    chunks_to_yield: list[StreamChunk] = field(default_factory=list)
    available_models: list[str] = field(default_factory=list)
    last_call_kwargs: dict[str, Any] = field(default_factory=dict)
    closed: bool = False
    raise_on_stream: Exception | None = None

    def __post_init__(self) -> None:
        # Skip Provider.__init__'s api_key handling on the stub.
        pass

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:  # type: ignore[override]
        self.last_call_kwargs = kwargs
        if self.raise_on_stream is not None:
            raise self.raise_on_stream
        yield from self.chunks_to_yield

    def parse_tool_calls(
        self, content: str, raw_response: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        return content, []

    def list_models(self) -> list[str]:
        return list(self.available_models)

    def close(self) -> None:
        self.closed = True


@dataclass
class StubPool:
    providers_with_creds: list[str] = field(default_factory=list)

    def providers(self) -> list[str]:
        return list(self.providers_with_creds)


def _make_cfg(tmp_path: Path, **overrides: Any) -> Config:
    cfg = Config()
    cfg.proxy_default_provider = overrides.get("proxy_default_provider", "anthropic")
    cfg.proxy_log_path = str(tmp_path / "proxy.jsonl")
    cfg.proxy_bodies_dir = str(tmp_path / "proxy_bodies")
    cfg.proxy_log_bodies = overrides.get("proxy_log_bodies", False)
    return cfg


def _build_app(cfg: Config, pool: StubPool, by_name: dict[str, StubProvider]):
    from athena.proxy.server import make_app

    def factory(name: str, model: str) -> tuple[Provider, str]:
        if name not in by_name:
            raise RuntimeError(f"no stub for provider {name!r}")
        return by_name[name], model

    return make_app(cfg=cfg, pool=pool, provider_factory=factory)  # type: ignore[arg-type]


async def _run_client(app, coro_factory):
    async with TestClient(TestServer(app)) as client:
        return await coro_factory(client)


def _parse_sse(text: str) -> list[Any]:
    out: list[Any] = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        body = line.removeprefix("data: ")
        out.append("[DONE]" if body == "[DONE]" else json.loads(body))
    return out


# ---------------------------------------------------------------------------
# /health and /v1/models
# ---------------------------------------------------------------------------


def test_health_ok(tmp_path) -> None:
    cfg = _make_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    app = _build_app(cfg, pool, {"anthropic": StubProvider()})

    async def run(client: TestClient) -> None:
        resp = await client.get("/health")
        assert resp.status == 200
        body = await resp.json()
        assert body["status"] == "ok"
        assert "anthropic" in body["providers"]

    asyncio.run(_run_client(app, run))


def test_models_lists_providers(tmp_path) -> None:
    cfg = _make_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    provider = StubProvider(
        name="anthropic",
        available_models=["claude-opus-4-7", "claude-sonnet-4-6"],
    )
    app = _build_app(cfg, pool, {"anthropic": provider})

    async def run(client: TestClient) -> None:
        resp = await client.get("/v1/models")
        assert resp.status == 200
        body = await resp.json()
        ids = sorted(m["id"] for m in body["data"])
        assert "claude-opus-4-7" in ids
        for m in body["data"]:
            assert m["owned_by"] == "anthropic"

    asyncio.run(_run_client(app, run))


# ---------------------------------------------------------------------------
# /v1/chat/completions — non-streaming
# ---------------------------------------------------------------------------


def test_chat_completions_nonstreaming_returns_object(tmp_path) -> None:
    cfg = _make_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    provider = StubProvider(
        name="anthropic",
        chunks_to_yield=[
            StreamChunk(kind="content", payload="Hello "),
            StreamChunk(kind="content", payload="world."),
            StreamChunk(
                kind="usage",
                payload={"prompt_tokens": 10, "completion_tokens": 3},
            ),
            StreamChunk(kind="end", payload={"reason": "stop"}),
        ],
    )
    app = _build_app(cfg, pool, {"anthropic": provider})

    async def run(client: TestClient) -> None:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["content"] == "Hello world."
        assert body["choices"][0]["finish_reason"] == "stop"
        assert body["usage"]["total_tokens"] == 13

    asyncio.run(_run_client(app, run))


# ---------------------------------------------------------------------------
# /v1/chat/completions — streaming SSE
# ---------------------------------------------------------------------------


def test_chat_completions_streams_openai_sse(tmp_path) -> None:
    cfg = _make_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    provider = StubProvider(
        name="anthropic",
        chunks_to_yield=[
            StreamChunk(kind="content", payload="Hello"),
            StreamChunk(kind="content", payload=" world."),
            StreamChunk(
                kind="usage",
                payload={"prompt_tokens": 4, "completion_tokens": 2},
            ),
            StreamChunk(kind="end", payload={"reason": "stop"}),
        ],
    )
    app = _build_app(cfg, pool, {"anthropic": provider})

    async def run(client: TestClient) -> None:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/event-stream")
        raw = (await resp.read()).decode("utf-8")
        chunks = _parse_sse(raw)
        # role chunk, content chunks, finish chunk, [DONE]
        assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
        contents = [
            c["choices"][0]["delta"].get("content")
            for c in chunks
            if c != "[DONE]" and c["choices"][0]["delta"].get("content") is not None
        ]
        assert "Hello" in contents and " world." in contents
        finish = [c for c in chunks if c != "[DONE]" and c["choices"][0].get("finish_reason")]
        assert finish[-1]["choices"][0]["finish_reason"] == "stop"
        assert chunks[-1] == "[DONE]"

    asyncio.run(_run_client(app, run))


def test_streaming_tool_call_emits_tool_calls_delta(tmp_path) -> None:
    cfg = _make_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    provider = StubProvider(
        name="anthropic",
        chunks_to_yield=[
            StreamChunk(
                kind="tool_call",
                payload={
                    "id": "toolu_1",
                    "name": "search",
                    "arguments": '{"q":"foo"}',
                },
            ),
            StreamChunk(kind="end", payload={"reason": "tool_use"}),
        ],
    )
    app = _build_app(cfg, pool, {"anthropic": provider})

    async def run(client: TestClient) -> None:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "search"}],
                "stream": True,
            },
        )
        raw = (await resp.read()).decode("utf-8")
        chunks = _parse_sse(raw)
        tool_chunks = [
            c for c in chunks if c != "[DONE]" and c["choices"][0]["delta"].get("tool_calls")
        ]
        assert len(tool_chunks) == 1
        tc = tool_chunks[0]["choices"][0]["delta"]["tool_calls"][0]
        assert tc["function"]["name"] == "search"
        finish = [c for c in chunks if c != "[DONE]" and c["choices"][0].get("finish_reason")]
        assert finish[-1]["choices"][0]["finish_reason"] == "tool_calls"

    asyncio.run(_run_client(app, run))


# ---------------------------------------------------------------------------
# Routing + error handling
# ---------------------------------------------------------------------------


def test_provider_header_overrides_route(tmp_path) -> None:
    cfg = _make_cfg(tmp_path, proxy_default_provider="anthropic")
    pool = StubPool(providers_with_creds=["anthropic", "openai"])
    openai = StubProvider(
        name="openai",
        chunks_to_yield=[
            StreamChunk(kind="content", payload="from-openai"),
            StreamChunk(kind="end", payload={"reason": "stop"}),
        ],
    )
    anthropic = StubProvider(
        name="anthropic",
        chunks_to_yield=[StreamChunk(kind="end", payload={"reason": "stop"})],
    )
    app = _build_app(cfg, pool, {"anthropic": anthropic, "openai": openai})

    async def run(client: TestClient) -> None:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",  # would route anthropic
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"X-Athena-Provider": "openai"},
        )
        body = await resp.json()
        assert body["choices"][0]["message"]["content"] == "from-openai"

    asyncio.run(_run_client(app, run))


def test_no_credentials_returns_openai_error(tmp_path) -> None:
    """No usable providers at all → 400 with an OpenAI-shaped error."""
    cfg = _make_cfg(tmp_path, proxy_default_provider="openai")
    pool = StubPool(providers_with_creds=[])
    app = _build_app(cfg, pool, {})

    async def run(client: TestClient) -> None:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "some-model",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status == 400
        body = await resp.json()
        assert "error" in body
        assert "default provider" in body["error"]["message"]
        assert body["error"]["type"] == "invalid_request_error"

    asyncio.run(_run_client(app, run))


def test_resolver_runtime_error_returns_503(tmp_path) -> None:
    """A factory that raises RuntimeError (no credentials path)
    surfaces as an OpenAI-shaped 503."""
    cfg = _make_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    app_no_factory = _build_app(cfg, pool, {})  # factory will raise

    async def run(client: TestClient) -> None:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status == 503
        body = await resp.json()
        assert body["error"]["type"] == "provider_unavailable"

    asyncio.run(_run_client(app_no_factory, run))


def test_embeddings_endpoint_returns_501(tmp_path) -> None:
    cfg = _make_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    app = _build_app(cfg, pool, {"anthropic": StubProvider()})

    async def run(client: TestClient) -> None:
        resp = await client.post(
            "/v1/embeddings",
            json={"model": "text-embedding-3-small", "input": "x"},
        )
        assert resp.status == 501
        body = await resp.json()
        assert body["error"]["type"] == "not_implemented"

    asyncio.run(_run_client(app, run))


def test_invalid_json_body_returns_400(tmp_path) -> None:
    cfg = _make_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    app = _build_app(cfg, pool, {"anthropic": StubProvider()})

    async def run(client: TestClient) -> None:
        resp = await client.post(
            "/v1/chat/completions",
            data=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
        body = await resp.json()
        assert body["error"]["type"] == "invalid_request_error"

    asyncio.run(_run_client(app, run))


# ---------------------------------------------------------------------------
# Proxy logging
# ---------------------------------------------------------------------------


def test_proxy_logs_each_request(tmp_path) -> None:
    cfg = _make_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    provider = StubProvider(
        name="anthropic",
        chunks_to_yield=[
            StreamChunk(kind="content", payload="hi"),
            StreamChunk(
                kind="usage",
                payload={"prompt_tokens": 5, "completion_tokens": 1},
            ),
            StreamChunk(kind="end", payload={"reason": "stop"}),
        ],
    )
    app = _build_app(cfg, pool, {"anthropic": provider})
    log_path = Path(cfg.proxy_log_path)
    assert not log_path.exists()

    async def run(client: TestClient) -> None:
        await client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"User-Agent": "TestClient/1.0"},
        )

    asyncio.run(_run_client(app, run))

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["client_ua"] == "TestClient/1.0"
    assert record["provider_used"] == "anthropic"
    assert record["tokens_in"] == 5
    assert record["tokens_out"] == 1


def test_streaming_log_records_usage(tmp_path) -> None:
    cfg = _make_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    provider = StubProvider(
        name="anthropic",
        chunks_to_yield=[
            StreamChunk(kind="content", payload="ok"),
            StreamChunk(
                kind="usage",
                payload={"prompt_tokens": 7, "completion_tokens": 2},
            ),
            StreamChunk(kind="end", payload={"reason": "stop"}),
        ],
    )
    app = _build_app(cfg, pool, {"anthropic": provider})

    async def run(client: TestClient) -> None:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
        await resp.read()

    asyncio.run(_run_client(app, run))

    log_path = Path(cfg.proxy_log_path)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    assert record["tokens_in"] == 7
    assert record["tokens_out"] == 2
    assert record["request_summary"]["stream"] is True
