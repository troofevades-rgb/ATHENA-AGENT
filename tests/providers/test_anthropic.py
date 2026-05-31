"""AnthropicProvider — SSE parsing, system hoisting, tool conversion."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from athena.providers import get_provider_class
from athena.providers.anthropic import AnthropicProvider


def _sse(*events: dict) -> bytes:
    """Serialize a sequence of Anthropic SSE events."""
    return b"".join(
        b"event: "
        + (e.get("type", "?").encode("utf-8"))
        + b"\n"
        + b"data: "
        + json.dumps(e).encode("utf-8")
        + b"\n\n"
        for e in events
    )


@pytest.fixture
def provider():
    p = AnthropicProvider(api_key="sk-ant-test", base_url="https://api.anthropic.test/v1")
    yield p
    p.close()


def test_registered_under_name_anthropic():
    assert get_provider_class("anthropic") is AnthropicProvider


def test_stream_chat_with_system_extracted_to_top_level_field(provider):
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse(
                {
                    "type": "message_start",
                    "message": {"usage": {"input_tokens": 8, "output_tokens": 0}},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "hi"},
                },
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 1},
                },
                {"type": "message_stop"},
            ),
        )

    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(side_effect=_record)
        list(
            provider.stream_chat(
                model="claude-3-5-sonnet",
                messages=[
                    {"role": "system", "content": "be terse"},
                    {"role": "user", "content": "hi"},
                ],
            )
        )
    body = captured["body"]
    assert body["system"] == "be terse"
    # System message must NOT appear in messages.
    assert all(m.get("role") != "system" for m in body["messages"])


def test_stream_chat_yields_text_then_usage_then_end(provider):
    sample = _sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 5, "output_tokens": 0}}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "hello "},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "world"},
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 3},
        },
        {"type": "message_stop"},
    )
    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(
            return_value=httpx.Response(200, content=sample)
        )
        chunks = list(
            provider.stream_chat(
                model="claude-3-5-sonnet", messages=[{"role": "user", "content": "x"}]
            )
        )
    kinds = [c.kind for c in chunks]
    assert kinds == ["content", "content", "usage", "end"]
    assert chunks[-2].payload == {"prompt_tokens": 5, "completion_tokens": 3}
    assert chunks[-1].payload == {"reason": "end_turn"}


def test_tools_converted_to_anthropic_schema(provider):
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse(
                {"type": "message_start", "message": {"usage": {}}},
                {"type": "message_stop"},
            ),
        )

    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": "Read",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        }
    ]
    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(side_effect=_record)
        list(
            provider.stream_chat(
                model="claude-3-5-sonnet",
                messages=[{"role": "user", "content": "x"}],
                tools=openai_tools,
            )
        )
    tools = captured["body"]["tools"]
    assert tools[0]["name"] == "Read"
    assert tools[0]["description"] == "Read a file"
    # OpenAI's "parameters" → Anthropic's "input_schema".
    assert "input_schema" in tools[0]
    assert "parameters" not in tools[0]


def test_tool_use_block_assembled_from_delta_stream(provider):
    """Anthropic streams tool calls as start → input_json_deltas → stop.
    The provider accumulates and emits one tool_call chunk."""
    sample = _sse(
        {"type": "message_start", "message": {"usage": {}}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "name": "Read", "id": "tu_1"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": ' "/tmp/x"}'},
        },
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        {"type": "message_stop"},
    )
    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(
            return_value=httpx.Response(200, content=sample)
        )
        chunks = list(
            provider.stream_chat(
                model="claude-3-5-sonnet", messages=[{"role": "user", "content": "x"}]
            )
        )
    tool_chunks = [c for c in chunks if c.kind == "tool_call"]
    assert len(tool_chunks) == 1
    assert tool_chunks[0].payload["name"] == "Read"
    assert tool_chunks[0].payload["id"] == "tu_1"
    assert tool_chunks[0].payload["arguments"] == {"path": "/tmp/x"}


def test_429_propagates_to_caller(provider):
    """A 429 response surfaces to the caller. Since T2-03 the
    provider's stream_chat is wrapped in with_retry; with retries
    disabled the underlying httpx.HTTPStatusError still propagates."""
    provider._retry_max = 0  # disable retry for this assertion
    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(
            return_value=httpx.Response(429, json={"error": "rate limited"})
        )
        from athena.providers.retry_utils import RetryBudgetExceeded

        with pytest.raises((httpx.HTTPStatusError, RetryBudgetExceeded)):
            list(
                provider.stream_chat(
                    model="claude-3-5-sonnet",
                    messages=[{"role": "user", "content": "x"}],
                )
            )


def test_payload_omits_temperature_for_deprecated_opus_4_7(provider):
    """``claude-opus-4-7`` rejects ``temperature`` with
    ``"temperature is deprecated for this model"`` (400). Pin from
    dogfood: the field must be omitted from the payload, not sent
    with a default."""
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse(
                {"type": "message_start", "message": {"usage": {}}},
                {"type": "message_stop"},
            ),
        )

    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(side_effect=_record)
        list(
            provider.stream_chat(
                model="claude-opus-4-7",
                messages=[{"role": "user", "content": "x"}],
            )
        )
    assert "temperature" not in captured["body"]


def test_payload_omits_temperature_for_date_suffixed_opus_4_7(provider):
    """The deprecation also covers the date-suffixed variant
    (``claude-opus-4-7-20251201``) -- substring match catches both."""
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse(
                {"type": "message_start", "message": {"usage": {}}},
                {"type": "message_stop"},
            ),
        )

    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(side_effect=_record)
        list(
            provider.stream_chat(
                model="claude-opus-4-7-20251201",
                messages=[{"role": "user", "content": "x"}],
            )
        )
    assert "temperature" not in captured["body"]


def test_payload_omits_temperature_for_sonnet_4_6(provider):
    """Same family rule for ``claude-sonnet-4-6``."""
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse(
                {"type": "message_start", "message": {"usage": {}}},
                {"type": "message_stop"},
            ),
        )

    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(side_effect=_record)
        list(
            provider.stream_chat(
                model="claude-sonnet-4-6",
                messages=[{"role": "user", "content": "x"}],
            )
        )
    assert "temperature" not in captured["body"]


def test_payload_includes_temperature_for_pre_deprecation_models(provider):
    """Older models still accept ``temperature``. Quiet path so the
    deprecation omission means something when it fires.

    Covers ``claude-3-5-sonnet`` (legacy), ``claude-sonnet-4-5``
    (current 4.5 series, not yet deprecated), and
    ``claude-haiku-4-5`` (4.5 Haiku)."""
    def _capture_and_call(model: str) -> dict:
        bucket: dict = {}

        def _record(request):
            bucket["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                content=_sse(
                    {"type": "message_start", "message": {"usage": {}}},
                    {"type": "message_stop"},
                ),
            )

        with respx.mock() as m:
            m.post("https://api.anthropic.test/v1/messages").mock(side_effect=_record)
            list(
                provider.stream_chat(
                    model=model,
                    messages=[{"role": "user", "content": "x"}],
                )
            )
        return bucket

    for model in (
        "claude-3-5-sonnet-20241022",
        "claude-sonnet-4-5-20250929",
        "claude-haiku-4-5-20251001",
    ):
        body = _capture_and_call(model)["body"]
        assert "temperature" in body, (
            f"{model} should still receive temperature"
        )


def test_payload_includes_max_tokens_default(provider):
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse(
                {"type": "message_start", "message": {"usage": {}}},
                {"type": "message_stop"},
            ),
        )

    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(side_effect=_record)
        list(
            provider.stream_chat(
                model="claude-3-5-sonnet",
                messages=[{"role": "user", "content": "x"}],
            )
        )
    # Anthropic REQUIRES max_tokens; the provider supplies a default.
    assert captured["body"]["max_tokens"] > 0


def test_anthropic_version_header_set():
    p = AnthropicProvider(api_key="k", anthropic_version="2026-01-01")
    try:
        assert p._client.headers["anthropic-version"] == "2026-01-01"
        assert p._client.headers["x-api-key"] == "k"
    finally:
        p.close()


def test_list_models_returns_ids(provider):
    """GET /v1/models returns {"data": [{id, type, ...}], "has_more": bool}."""
    with respx.mock() as m:
        m.get("https://api.anthropic.test/v1/models").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "claude-haiku-4-5-20251001", "type": "model"},
                        {"id": "claude-sonnet-4-7", "type": "model"},
                        {"id": "claude-opus-4-7", "type": "model"},
                    ],
                    "has_more": False,
                },
            )
        )
        names = provider.list_models()
    assert names == [
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-7",
        "claude-opus-4-7",
    ]


def test_list_models_handles_empty(provider):
    with respx.mock() as m:
        m.get("https://api.anthropic.test/v1/models").mock(
            return_value=httpx.Response(200, json={"data": [], "has_more": False})
        )
        assert provider.list_models() == []


def test_list_models_propagates_auth_failure(provider):
    with respx.mock() as m:
        m.get("https://api.anthropic.test/v1/models").mock(
            return_value=httpx.Response(
                401,
                json={"error": {"type": "authentication_error"}},
            )
        )
        with pytest.raises(httpx.HTTPStatusError):
            provider.list_models()


def test_malformed_sse_lines_skipped(provider):
    """A non-JSON data line shouldn't crash the parser."""
    body = (
        b"event: ping\ndata: notjson\n\n"
        b"event: message_start\ndata: "
        + json.dumps({"type": "message_start", "message": {"usage": {}}}).encode("utf-8")
        + b"\n\n"
        b"event: message_stop\ndata: "
        + json.dumps({"type": "message_stop"}).encode("utf-8")
        + b"\n\n"
    )
    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(
            return_value=httpx.Response(200, content=body)
        )
        chunks = list(
            provider.stream_chat(
                model="claude-3-5-sonnet", messages=[{"role": "user", "content": "x"}]
            )
        )
    # Stream terminates cleanly despite the bad line.
    assert chunks[-1].kind == "end"


# ---------------------------------------------------------------------------
# T2-02: rate-limit header capture + preemptive throttle
# ---------------------------------------------------------------------------


def test_rate_limit_headers_captured_from_response(provider):
    """After a successful stream_chat, the provider stores a
    RateLimitTracker parsed from the anthropic-ratelimit-* response
    headers."""
    sample = _sse({"type": "message_start", "message": {"usage": {}}}, {"type": "message_stop"})
    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(
            return_value=httpx.Response(
                200,
                content=sample,
                headers={
                    "anthropic-ratelimit-requests-limit": "50",
                    "anthropic-ratelimit-requests-remaining": "47",
                    "anthropic-ratelimit-requests-reset": "2099-01-01T00:00:00Z",
                    "anthropic-ratelimit-tokens-limit": "30000",
                    "anthropic-ratelimit-tokens-remaining": "28440",
                },
            )
        )
        list(
            provider.stream_chat(
                model="claude-3-5-sonnet", messages=[{"role": "user", "content": "x"}]
            )
        )

    state = provider.get_rate_limit_state()
    assert state, "rate-limit state was not captured"
    tracker = next(iter(state.values()))
    assert tracker.limit_requests_min == 50
    assert tracker.remaining_requests_min == 47
    assert tracker.limit_tokens_min == 30000


def test_no_rate_limit_headers_leaves_state_empty(provider):
    """A response with no rate-limit headers does not populate the
    tracker state (and does not crash)."""
    sample = _sse({"type": "message_start", "message": {"usage": {}}}, {"type": "message_stop"})
    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(
            return_value=httpx.Response(200, content=sample, headers={})
        )
        list(
            provider.stream_chat(
                model="claude-3-5-sonnet", messages=[{"role": "user", "content": "x"}]
            )
        )
    assert provider.get_rate_limit_state() == {}


def test_preemptive_throttle_sleeps_when_near_limit(provider, monkeypatch):
    """If the previous tracker says we should throttle, the next
    stream_chat sleeps before issuing the request."""
    import time as _time

    from athena.providers.rate_limit_tracker import RateLimitTracker

    now = _time.time()
    # Pre-seed: previous response left us with 1/100 requests remaining
    # (99% used), reset in 15s.
    cred_id = provider._current_credential_id()
    provider._rate_limit_state[cred_id] = RateLimitTracker(
        provider="anthropic",
        captured_at=now,
        limit_requests_min=100,
        remaining_requests_min=1,
        reset_requests_min_at=now + 15.0,
    )

    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "athena.providers.anthropic.time.sleep",
        lambda s: sleep_calls.append(s),
    )

    sample = _sse({"type": "message_start", "message": {"usage": {}}}, {"type": "message_stop"})
    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(
            return_value=httpx.Response(200, content=sample, headers={})
        )
        list(
            provider.stream_chat(
                model="claude-3-5-sonnet", messages=[{"role": "user", "content": "x"}]
            )
        )

    assert sleep_calls, "expected at least one preemptive sleep call"
    # Sleep duration matches throttle_seconds (capped at 60).
    assert 10 < sleep_calls[0] <= 60


def test_no_throttle_when_under_threshold(provider, monkeypatch):
    """A previous tracker showing plenty of headroom does NOT trigger
    a preemptive sleep."""
    import time as _time

    from athena.providers.rate_limit_tracker import RateLimitTracker

    cred_id = provider._current_credential_id()
    provider._rate_limit_state[cred_id] = RateLimitTracker(
        provider="anthropic",
        captured_at=_time.time(),
        limit_requests_min=100,
        remaining_requests_min=50,  # 50% used, well under 95% threshold
        reset_requests_min_at=_time.time() + 15.0,
    )

    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "athena.providers.anthropic.time.sleep",
        lambda s: sleep_calls.append(s),
    )

    sample = _sse({"type": "message_start", "message": {"usage": {}}}, {"type": "message_stop"})
    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(
            return_value=httpx.Response(200, content=sample, headers={})
        )
        list(
            provider.stream_chat(
                model="claude-3-5-sonnet", messages=[{"role": "user", "content": "x"}]
            )
        )

    assert sleep_calls == [], f"unexpected sleep calls: {sleep_calls}"


# ---------------------------------------------------------------------------
# T2-03: retry wrapping
# ---------------------------------------------------------------------------


def test_5xx_retries_then_succeeds(provider, monkeypatch):
    """A 503 followed by a 200 produces a successful stream — the
    classifier flagged 503 as SERVER_5XX + RETRY, with_retry slept
    (mocked) and re-called the operation."""
    monkeypatch.setattr("athena.providers.retry_utils.time.sleep", lambda s: None)

    sample = _sse(
        {"type": "message_start", "message": {"usage": {}}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}},
        {"type": "message_stop"},
    )
    with respx.mock() as m:
        route = m.post("https://api.anthropic.test/v1/messages")
        route.side_effect = [
            httpx.Response(503, text="oops"),
            httpx.Response(200, content=sample),
        ]
        chunks = list(
            provider.stream_chat(
                model="claude-3-5-sonnet",
                messages=[{"role": "user", "content": "x"}],
            )
        )
    contents = [c.payload for c in chunks if c.kind == "content"]
    assert "".join(contents) == "ok"


def test_4xx_aborts_without_retry(provider, monkeypatch):
    """A 401 is classified as CLIENT_4XX + ABORT; with_retry re-raises
    the original HTTPStatusError without retrying."""
    call_count = 0
    original_sleep = __import__("time").sleep
    monkeypatch.setattr("athena.providers.retry_utils.time.sleep", lambda s: None)

    def _hook(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, text="unauthorized")

    with respx.mock() as m:
        m.post("https://api.anthropic.test/v1/messages").mock(side_effect=_hook)
        with pytest.raises(httpx.HTTPStatusError):
            list(
                provider.stream_chat(
                    model="claude-3-5-sonnet",
                    messages=[{"role": "user", "content": "x"}],
                )
            )
    assert call_count == 1  # ABORT means exactly one upstream call
