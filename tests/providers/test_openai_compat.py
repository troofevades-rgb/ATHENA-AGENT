"""OpenAICompatProvider — generic OpenAI-shaped servers (vLLM, llama.cpp, ...)."""
from __future__ import annotations

import json

import httpx
import respx

from athena.providers import StreamChunk, get_provider_class
from athena.providers.openai_compat import OpenAICompatProvider


def _sse(*events: dict) -> bytes:
    return b"".join(
        b"data: " + json.dumps(e).encode("utf-8") + b"\n\n" for e in events
    ) + b"data: [DONE]\n\n"


def test_registered_under_name_openai_compat():
    assert get_provider_class("openai_compat") is OpenAICompatProvider


def test_vllm_endpoint_compatible():
    p = OpenAICompatProvider(host="http://vllm.local:8000", api_key=None)
    try:
        sample = _sse(
            {"choices": [{"delta": {"content": "hi"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 1}},
        )
        with respx.mock() as m:
            m.post("http://vllm.local:8000/v1/chat/completions").mock(
                return_value=httpx.Response(200, content=sample)
            )
            chunks = list(p.stream_chat(
                model="meta-llama/Llama-3.1-8B-Instruct",
                messages=[{"role": "user", "content": "ping"}],
            ))
    finally:
        p.close()
    contents = [c.payload for c in chunks if c.kind == "content"]
    assert "".join(contents) == "hi"


def test_llamacpp_endpoint_compatible():
    """llama.cpp's server uses a slightly different default port but the
    same API shape; the provider just needs the host to point at it."""
    p = OpenAICompatProvider(host="http://localhost:8080", api_key=None)
    try:
        sample = _sse(
            {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        )
        with respx.mock() as m:
            m.post("http://localhost:8080/v1/chat/completions").mock(
                return_value=httpx.Response(200, content=sample)
            )
            chunks = list(p.stream_chat(
                model="llama3",
                messages=[{"role": "user", "content": "ping"}],
            ))
    finally:
        p.close()
    assert any(c.kind == "content" for c in chunks)


def test_host_v1_suffix_idempotent():
    """Whether caller passes 'http://x:8000' or 'http://x:8000/v1', the
    final base_url should end in /v1 exactly once."""
    p1 = OpenAICompatProvider(host="http://x.local:8000")
    p2 = OpenAICompatProvider(host="http://x.local:8000/v1")
    p3 = OpenAICompatProvider(host="http://x.local:8000/")
    try:
        assert p1.base_url == "http://x.local:8000/v1"
        assert p2.base_url == "http://x.local:8000/v1"
        assert p3.base_url == "http://x.local:8000/v1"
    finally:
        p1.close(); p2.close(); p3.close()


def test_no_auth_header_when_api_key_absent():
    """Local servers like vLLM / llama.cpp typically don't require auth."""
    p = OpenAICompatProvider(host="http://localhost:8000")
    try:
        assert "authorization" not in p._client.headers
    finally:
        p.close()


def test_auth_header_when_api_key_provided():
    p = OpenAICompatProvider(host="http://localhost:8000", api_key="sk-test")
    try:
        assert p._client.headers["authorization"] == "Bearer sk-test"
    finally:
        p.close()
