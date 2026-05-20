"""End-to-end server tests with FastAPI TestClient (T3-01.6).

A stub provider replaces athena's runtime resolver so tests stay
hermetic — no network, no credential pool entanglement.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from athena.config import Config
from athena.providers.base import Provider, StreamChunk

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@dataclass
class StubProvider(Provider):
    """In-memory fake. Each call to stream_chat replays the configured
    chunks. ``available_models`` populates :meth:`list_models`."""

    name: str = "anthropic"
    chunks_to_yield: list[StreamChunk] = field(default_factory=list)
    available_models: list[str] = field(default_factory=list)
    last_call_kwargs: dict[str, Any] = field(default_factory=dict)
    closed: bool = False
    raise_on_stream: Exception | None = None

    def __post_init__(self) -> None:
        # Skip Provider.__init__ — no api_key on stub
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
    """Just enough of CredentialPool's surface for the proxy server."""

    providers_with_creds: list[str] = field(default_factory=list)

    def providers(self) -> list[str]:
        return list(self.providers_with_creds)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_cfg(tmp_path: Path, **overrides: Any) -> Config:
    cfg = Config()
    cfg.proxy_default_provider = overrides.get("proxy_default_provider", "anthropic")
    cfg.proxy_log_path = str(tmp_path / "proxy.jsonl")
    cfg.proxy_bodies_dir = str(tmp_path / "proxy_bodies")
    cfg.proxy_log_bodies = overrides.get("proxy_log_bodies", False)
    return cfg


def _build_app(
    cfg: Config,
    pool: StubPool,
    providers_by_name: dict[str, StubProvider],
) -> Any:
    from athena.proxy.server import make_app

    def factory(name: str, model: str) -> tuple[Provider, str]:
        if name not in providers_by_name:
            raise RuntimeError(f"no stub for provider {name!r}")
        return providers_by_name[name], model

    return make_app(cfg=cfg, pool=pool, provider_factory=factory)  # type: ignore[arg-type]


def _decode_sse_stream(raw: bytes) -> list[Any]:
    """Pull `data: ` chunks out of the raw SSE body and parse them."""
    out: list[Any] = []
    for line in raw.decode("utf-8").splitlines():
        if not line.startswith("data: "):
            continue
        payload = line.removeprefix("data: ")
        if payload == "[DONE]":
            out.append("[DONE]")
        else:
            out.append(json.loads(payload))
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_list_models_returns_available_models(tmp_path) -> None:
    cfg = _make_test_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    provider = StubProvider(
        name="anthropic",
        available_models=["claude-opus-4-7", "claude-sonnet-4-6"],
    )
    app = _build_app(cfg, pool, {"anthropic": provider})

    with TestClient(app) as client:
        response = client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        ids = sorted(m["id"] for m in data["data"])
        assert "claude-opus-4-7" in ids
        assert "claude-sonnet-4-6" in ids
        for m in data["data"]:
            assert m["owned_by"] == "anthropic"


def test_chat_completions_non_streaming_anthropic_route(tmp_path) -> None:
    cfg = _make_test_cfg(tmp_path)
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

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["content"] == "Hello world."
        assert body["choices"][0]["finish_reason"] == "stop"
        assert body["usage"]["total_tokens"] == 13
        assert body["model"] == "claude-sonnet-4-6"

    # provider.last_call_kwargs should reflect what we sent.
    assert provider.last_call_kwargs["model"] == "claude-sonnet-4-6"
    assert provider.last_call_kwargs["messages"] == [{"role": "user", "content": "hi"}]


def test_chat_completions_streaming_anthropic_route(tmp_path) -> None:
    cfg = _make_test_cfg(tmp_path)
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

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
        assert response.status_code == 200, response.text
        chunks = _decode_sse_stream(response.content)
        # role chunk, content chunks, finish chunk, [DONE]
        assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
        contents = [
            c["choices"][0]["delta"].get("content", "")
            for c in chunks
            if c != "[DONE]" and "delta" in c["choices"][0]
        ]
        assert "Hello" in contents
        assert " world." in contents
        finish_chunks = [
            c for c in chunks if c != "[DONE]" and c["choices"][0].get("finish_reason")
        ]
        assert finish_chunks[-1]["choices"][0]["finish_reason"] == "stop"
        assert chunks[-1] == "[DONE]"


def test_streaming_tool_call_emits_tool_calls_delta(tmp_path) -> None:
    cfg = _make_test_cfg(tmp_path)
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

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "search"}],
                "stream": True,
            },
        )
        chunks = _decode_sse_stream(response.content)
        tool_chunks = [
            c for c in chunks if c != "[DONE]" and c["choices"][0]["delta"].get("tool_calls")
        ]
        assert len(tool_chunks) == 1
        tc = tool_chunks[0]["choices"][0]["delta"]["tool_calls"][0]
        assert tc["id"] == "toolu_1"
        assert tc["function"]["name"] == "search"
        assert tc["function"]["arguments"] == '{"q":"foo"}'
        # finish reason should be tool_calls
        finish_chunks = [
            c for c in chunks if c != "[DONE]" and c["choices"][0].get("finish_reason")
        ]
        assert finish_chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"


def test_provider_header_overrides_route(tmp_path) -> None:
    cfg = _make_test_cfg(tmp_path, proxy_default_provider="anthropic")
    pool = StubPool(providers_with_creds=["anthropic", "openai"])
    anthropic = StubProvider(
        name="anthropic",
        chunks_to_yield=[StreamChunk(kind="end", payload={"reason": "stop"})],
    )
    openai = StubProvider(
        name="openai",
        chunks_to_yield=[
            StreamChunk(kind="content", payload="from-openai"),
            StreamChunk(kind="end", payload={"reason": "stop"}),
        ],
    )
    app = _build_app(cfg, pool, {"anthropic": anthropic, "openai": openai})

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",  # would route to anthropic
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"X-Athena-Provider": "openai"},
        )
        assert response.status_code == 200, response.text
        # openai stub's content should be what we got
        assert response.json()["choices"][0]["message"]["content"] == "from-openai"


def test_unavailable_provider_returns_400(tmp_path) -> None:
    cfg = _make_test_cfg(tmp_path, proxy_default_provider="openai")
    # Pool has nothing usable — and proxy_default_provider isn't in it
    pool = StubPool(providers_with_creds=[])
    app = _build_app(cfg, pool, {})

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "some-random-model",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 400
        assert "default provider" in response.json()["detail"]


def test_embeddings_endpoint_returns_501(tmp_path) -> None:
    cfg = _make_test_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    app = _build_app(cfg, pool, {"anthropic": StubProvider()})
    with TestClient(app) as client:
        response = client.post(
            "/v1/embeddings", json={"model": "text-embedding-3-small", "input": "x"}
        )
        assert response.status_code == 501


def test_proxy_logs_each_request(tmp_path) -> None:
    cfg = _make_test_cfg(tmp_path)
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

    with TestClient(app) as client:
        client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"User-Agent": "TestClient/1.0"},
        )

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["client_ua"] == "TestClient/1.0"
    assert record["model_requested"] == "claude-sonnet-4-6"
    assert record["provider_used"] == "anthropic"
    assert record["tokens_in"] == 5
    assert record["tokens_out"] == 1


def test_upstream_error_surfaces_as_502(tmp_path) -> None:
    cfg = _make_test_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    provider = StubProvider(
        name="anthropic",
        raise_on_stream=RuntimeError("upstream blew up"),
    )
    app = _build_app(cfg, pool, {"anthropic": provider})

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 502
        assert "upstream blew up" in response.json()["detail"]


def test_streaming_provider_error_emits_error_chunk(tmp_path) -> None:
    cfg = _make_test_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    provider = StubProvider(
        name="anthropic",
        raise_on_stream=RuntimeError("stream blew up"),
    )
    app = _build_app(cfg, pool, {"anthropic": provider})

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
        # Streaming responses always return 200; errors are inside the
        # SSE stream so the client can surface them inline.
        assert response.status_code == 200
        raw = response.content.decode("utf-8")
        assert "stream blew up" in raw
        assert "[DONE]" in raw


def test_log_bodies_writes_full_payload(tmp_path) -> None:
    cfg = _make_test_cfg(tmp_path, proxy_log_bodies=True)
    pool = StubPool(providers_with_creds=["anthropic"])
    provider = StubProvider(
        name="anthropic",
        chunks_to_yield=[
            StreamChunk(kind="content", payload="ok"),
            StreamChunk(kind="end", payload={"reason": "stop"}),
        ],
    )
    app = _build_app(cfg, pool, {"anthropic": provider})

    with TestClient(app) as client:
        client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    bodies = list(Path(cfg.proxy_bodies_dir).iterdir())
    assert len(bodies) == 1
    payload = json.loads(bodies[0].read_text(encoding="utf-8"))
    assert payload["request"]["messages"] == [{"role": "user", "content": "hi"}]
    assert payload["response"]["choices"][0]["message"]["content"] == "ok"


def test_finishes_default_to_stop_when_provider_omits_end(tmp_path) -> None:
    """A misbehaving provider that doesn't emit an ``end`` chunk
    should still get a terminating finish_reason in the SSE stream."""
    cfg = _make_test_cfg(tmp_path)
    pool = StubPool(providers_with_creds=["anthropic"])
    provider = StubProvider(
        name="anthropic",
        chunks_to_yield=[StreamChunk(kind="content", payload="oops")],
    )
    app = _build_app(cfg, pool, {"anthropic": provider})

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
        chunks = _decode_sse_stream(response.content)
        finish_chunks = [
            c for c in chunks if c != "[DONE]" and c["choices"][0].get("finish_reason")
        ]
        assert finish_chunks[-1]["choices"][0]["finish_reason"] == "stop"
        assert chunks[-1] == "[DONE]"
