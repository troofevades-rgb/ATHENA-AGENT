"""XAIProvider -- Grok chat models at api.x.ai."""

from __future__ import annotations

import json

import httpx
import respx

from athena.providers import get_provider_class
from athena.providers.xai import XAIProvider


def _sse(*events: dict) -> bytes:
    return (
        b"".join(b"data: " + json.dumps(e).encode("utf-8") + b"\n\n" for e in events)
        + b"data: [DONE]\n\n"
    )


def test_registered_under_name_xai():
    assert get_provider_class("xai") is XAIProvider


def test_static_capabilities_match_grok_surface():
    """Capabilities pin the broker-visible shape of the provider."""
    caps = XAIProvider.static_capabilities()
    assert caps.tool_calls is True
    assert caps.streaming is True
    assert caps.vision is True
    assert caps.prompt_caching is True
    # xAI caches server-side automatically (no client-side markers).
    assert caps.anthropic_cache_markers is False
    assert caps.native_format == "openai"
    assert caps.is_local is False


def test_stream_chat_basic():
    p = XAIProvider(api_key="xai-test-key")
    try:
        sample = _sse(
            {"choices": [{"delta": {"content": "Grok here"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 3}},
        )
        with respx.mock() as m:
            m.post("https://api.x.ai/v1/chat/completions").mock(
                return_value=httpx.Response(200, content=sample)
            )
            chunks = list(
                p.stream_chat(
                    model="grok-2-1212",
                    messages=[{"role": "user", "content": "hi"}],
                )
            )
    finally:
        p.close()
    contents = [c.payload for c in chunks if c.kind == "content"]
    assert "Grok here" in "".join(contents)
    end = chunks[-1]
    assert end.kind == "end" and end.payload["reason"] == "stop"


def test_authorization_bearer_header_set():
    p = XAIProvider(api_key="xai-abc")
    try:
        assert p._client.headers["authorization"] == "Bearer xai-abc"
    finally:
        p.close()


def test_base_url_override():
    """Allow pointing at a non-default endpoint (gateways, mocks)."""
    p = XAIProvider(
        api_key="k",
        base_url="https://gw.example.test/v1",
    )
    try:
        assert p.base_url == "https://gw.example.test/v1"
    finally:
        p.close()
