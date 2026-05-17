"""OpenRouterProvider — OpenAI-compat aggregator at openrouter.ai."""
from __future__ import annotations

import json

import httpx
import respx

from athena.providers import StreamChunk, get_provider_class
from athena.providers.openrouter import OpenRouterProvider


def _sse(*events: dict) -> bytes:
    return b"".join(
        b"data: " + json.dumps(e).encode("utf-8") + b"\n\n" for e in events
    ) + b"data: [DONE]\n\n"


def test_registered_under_name_openrouter():
    assert get_provider_class("openrouter") is OpenRouterProvider


def test_model_string_includes_vendor_prefix():
    """OpenRouter addresses models with 'vendor/model'. The provider just
    forwards whatever model string it's given."""
    p = OpenRouterProvider(api_key="sk-or-test")
    try:
        captured: dict = {}

        def _record(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, content=_sse(
                {"choices": [{"delta": {"content": "ok"},
                              "finish_reason": "stop"}]},
                {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
            ))

        with respx.mock() as m:
            m.post("https://openrouter.ai/api/v1/chat/completions").mock(
                side_effect=_record
            )
            list(p.stream_chat(
                model="anthropic/claude-3-5-sonnet",
                messages=[{"role": "user", "content": "hi"}],
            ))
        assert captured["body"]["model"] == "anthropic/claude-3-5-sonnet"
    finally:
        p.close()


def test_referer_and_title_headers_set():
    """OpenRouter's recommended client identification headers must be
    present so usage shows up against the right app in their dashboard."""
    p = OpenRouterProvider(api_key="sk-or-test")
    try:
        assert "HTTP-Referer" in p._client.headers
        assert "X-Title" in p._client.headers
        assert p._client.headers["X-Title"] == "athena"
    finally:
        p.close()


def test_referer_and_title_override_via_constructor():
    p = OpenRouterProvider(
        api_key="sk-or",
        referer="https://example.test/my-app",
        app_title="my-app",
    )
    try:
        assert p._client.headers["HTTP-Referer"] == "https://example.test/my-app"
        assert p._client.headers["X-Title"] == "my-app"
    finally:
        p.close()


def test_authorization_header_set():
    p = OpenRouterProvider(api_key="sk-or-12345")
    try:
        assert p._client.headers["authorization"] == "Bearer sk-or-12345"
    finally:
        p.close()
