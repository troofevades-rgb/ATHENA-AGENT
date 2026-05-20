"""OpenAIProvider — chat/completions SSE, tool-call delta assembly."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from athena.providers import get_provider_class
from athena.providers.openai import OpenAICompatibleProvider, OpenAIProvider


def _sse(*events: dict) -> bytes:
    return (
        b"".join(b"data: " + json.dumps(e).encode("utf-8") + b"\n\n" for e in events)
        + b"data: [DONE]\n\n"
    )


@pytest.fixture
def provider():
    p = OpenAIProvider(api_key="sk-test", base_url="https://api.openai.test/v1")
    yield p
    p.close()


def test_registered_under_name_openai():
    assert get_provider_class("openai") is OpenAIProvider


def test_stream_chat_yields_content_chunks(provider):
    sample = _sse(
        {"choices": [{"delta": {"role": "assistant", "content": ""}}]},
        {"choices": [{"delta": {"content": "hello "}}]},
        {"choices": [{"delta": {"content": "world"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
    )
    with respx.mock() as m:
        m.post("https://api.openai.test/v1/chat/completions").mock(
            return_value=httpx.Response(200, content=sample)
        )
        chunks = list(
            provider.stream_chat(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hi"}],
            )
        )
    contents = [c.payload for c in chunks if c.kind == "content"]
    assert "".join(contents) == "hello world"
    usage = next(c for c in chunks if c.kind == "usage")
    assert usage.payload == {"prompt_tokens": 5, "completion_tokens": 2}
    end = chunks[-1]
    assert end.kind == "end"
    assert end.payload["reason"] == "stop"


def test_function_calls_emitted_as_tool_call_chunks(provider):
    """Tool calls arrive as delta fragments. The provider assembles them
    per index and emits one StreamChunk per index."""
    sample = _sse(
        {"choices": [{"delta": {"role": "assistant", "content": ""}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_abc",
                                "type": "function",
                                "function": {"name": "Read", "arguments": ""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"path":'}}]}}
            ]
        },
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ' "/tmp/x"}'}}]}}
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 8}},
    )
    with respx.mock() as m:
        m.post("https://api.openai.test/v1/chat/completions").mock(
            return_value=httpx.Response(200, content=sample)
        )
        chunks = list(
            provider.stream_chat(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "read /tmp/x"}],
            )
        )
    tools = [c for c in chunks if c.kind == "tool_call"]
    assert len(tools) == 1
    assert tools[0].payload["name"] == "Read"
    assert tools[0].payload["id"] == "call_abc"
    assert tools[0].payload["arguments"] == {"path": "/tmp/x"}


def test_max_tokens_respected(provider):
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse(
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 0}},
            ),
        )

    with respx.mock() as m:
        m.post("https://api.openai.test/v1/chat/completions").mock(side_effect=_record)
        list(
            provider.stream_chat(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "x"}],
                max_tokens=200,
            )
        )
    assert captured["body"]["max_tokens"] == 200


def test_temperature_and_stream_options_set(provider):
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse(
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {}},
            ),
        )

    with respx.mock() as m:
        m.post("https://api.openai.test/v1/chat/completions").mock(side_effect=_record)
        list(
            provider.stream_chat(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "x"}],
                temperature=0.1,
            )
        )
    body = captured["body"]
    assert body["temperature"] == 0.1
    assert body["stream"] is True
    assert body["stream_options"]["include_usage"] is True


def test_authorization_header_set():
    p = OpenAIProvider(api_key="sk-12345")
    try:
        assert p._client.headers["authorization"] == "Bearer sk-12345"
    finally:
        p.close()


def test_list_models_returns_ids(provider):
    """OpenAI's /v1/models returns {object:"list", data:[{id,...}]}."""
    with respx.mock() as m:
        m.get("https://api.openai.test/v1/models").mock(
            return_value=httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {"id": "gpt-4o", "object": "model"},
                        {"id": "gpt-4o-mini", "object": "model"},
                        {"id": "o1", "object": "model"},
                    ],
                },
            )
        )
        names = provider.list_models()
    assert "gpt-4o-mini" in names
    assert len(names) == 3


def test_list_models_inherited_by_subclasses():
    """OpenRouter / Nous / openai_compat get list_models() for free."""
    from athena.providers.openrouter import OpenRouterProvider

    p = OpenRouterProvider(api_key="sk-or-test")
    try:
        with respx.mock() as m:
            m.get("https://openrouter.ai/api/v1/models").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "data": [
                            {"id": "anthropic/claude-3-5-sonnet"},
                            {"id": "openai/gpt-4o"},
                        ],
                    },
                )
            )
            names = p.list_models()
        assert names == ["anthropic/claude-3-5-sonnet", "openai/gpt-4o"]
    finally:
        p.close()


def test_list_models_propagates_error(provider):
    with respx.mock() as m:
        m.get("https://api.openai.test/v1/models").mock(
            return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
        )
        with pytest.raises(httpx.HTTPStatusError):
            provider.list_models()


def test_429_propagates(provider):
    """Since T2-03 the provider's stream_chat is wrapped in with_retry;
    disabling retry keeps the original assertion (raw 429 propagates)."""
    provider._retry_max = 0
    from athena.providers.retry_utils import RetryBudgetExceeded

    with respx.mock() as m:
        m.post("https://api.openai.test/v1/chat/completions").mock(
            return_value=httpx.Response(429, json={"error": {"message": "rate"}})
        )
        with pytest.raises((httpx.HTTPStatusError, RetryBudgetExceeded)):
            list(
                provider.stream_chat(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "x"}],
                )
            )


def test_compat_base_class_allows_custom_base_url():
    """OpenAICompatibleProvider is the base for OpenAI-compat / OpenRouter
    / Nous; instantiating it with a custom base_url should work."""

    class _Concrete(OpenAICompatibleProvider):
        name = "concrete-test"

    p = _Concrete(api_key="k", base_url="https://my-server.invalid/v1")
    try:
        assert p.base_url == "https://my-server.invalid/v1"
    finally:
        p.close()


def test_compat_base_class_allows_extra_headers():
    """Subclasses pass through extra_headers — used by OpenRouter for
    HTTP-Referer and Nous for their own auth header in Prompt 8.4."""

    class _Concrete(OpenAICompatibleProvider):
        name = "concrete-test-2"

    p = _Concrete(api_key="k", extra_headers={"x-thing": "yes"})
    try:
        assert p._client.headers["x-thing"] == "yes"
    finally:
        p.close()


# ---------------------------------------------------------------------------
# T2-02: rate-limit header capture + preemptive throttle
# (logic lives on OpenAICompatibleProvider; OpenAIProvider inherits)
# ---------------------------------------------------------------------------


def test_rate_limit_headers_captured_from_response(provider):
    """Generic 12-header schema parses into the provider's tracker dict."""
    sample = _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    with respx.mock() as m:
        m.post("https://api.openai.test/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                content=sample,
                headers={
                    "x-ratelimit-limit-requests": "200",
                    "x-ratelimit-remaining-requests": "180",
                    "x-ratelimit-reset-requests": "60",
                    "x-ratelimit-limit-tokens": "100000",
                    "x-ratelimit-remaining-tokens": "85000",
                    "x-ratelimit-reset-tokens": "60",
                },
            )
        )
        list(
            provider.stream_chat(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "x"}],
            )
        )

    state = provider.get_rate_limit_state()
    assert state, "rate-limit state was not captured"
    tracker = next(iter(state.values()))
    assert tracker.limit_requests_min == 200
    assert tracker.remaining_requests_min == 180
    assert tracker.limit_tokens_min == 100000


def test_no_rate_limit_headers_leaves_state_empty(provider):
    """Endpoints that omit x-ratelimit-* (Ollama-shaped servers etc.)
    must not crash and must not populate state."""
    sample = _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    with respx.mock() as m:
        m.post("https://api.openai.test/v1/chat/completions").mock(
            return_value=httpx.Response(200, content=sample, headers={})
        )
        list(
            provider.stream_chat(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "x"}],
            )
        )
    assert provider.get_rate_limit_state() == {}


def test_preemptive_throttle_sleeps_when_near_limit(provider, monkeypatch):
    """OpenAI-family throttle behaves identically to Anthropic's."""
    import time as _time

    from athena.providers.rate_limit_tracker import RateLimitTracker

    now = _time.time()
    cred_id = provider._current_credential_id()
    provider._rate_limit_state[cred_id] = RateLimitTracker(
        provider="openai",
        captured_at=now,
        limit_tokens_min=10000,
        remaining_tokens_min=100,  # 99% used
        reset_tokens_min_at=now + 20.0,
    )

    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "athena.providers.openai.time.sleep",
        lambda s: sleep_calls.append(s),
    )

    sample = _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    with respx.mock() as m:
        m.post("https://api.openai.test/v1/chat/completions").mock(
            return_value=httpx.Response(200, content=sample, headers={})
        )
        list(
            provider.stream_chat(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "x"}],
            )
        )

    assert sleep_calls, "expected preemptive sleep call"
    assert 15 < sleep_calls[0] <= 60
