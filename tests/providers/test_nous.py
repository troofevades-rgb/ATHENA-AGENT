"""NousProvider — Nous Portal hosted models."""

from __future__ import annotations

import json

import httpx
import respx

from athena.providers import get_provider_class
from athena.providers.nous import NousProvider


def _sse(*events: dict) -> bytes:
    return (
        b"".join(b"data: " + json.dumps(e).encode("utf-8") + b"\n\n" for e in events)
        + b"data: [DONE]\n\n"
    )


def test_registered_under_name_nous():
    assert get_provider_class("nous") is NousProvider


def test_stream_chat_basic():
    p = NousProvider(api_key="nous-test-key")
    try:
        sample = _sse(
            {"choices": [{"delta": {"content": "Hermes here"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 3}},
        )
        with respx.mock() as m:
            m.post("https://inference-api.nousresearch.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, content=sample)
            )
            chunks = list(
                p.stream_chat(
                    model="Hermes-3-Llama-3.1-405B",
                    messages=[{"role": "user", "content": "hi"}],
                )
            )
    finally:
        p.close()
    contents = [c.payload for c in chunks if c.kind == "content"]
    assert "Hermes here" in "".join(contents)
    end = chunks[-1]
    assert end.kind == "end" and end.payload["reason"] == "stop"


def test_authorization_bearer_header_set():
    p = NousProvider(api_key="nous-abc")
    try:
        assert p._client.headers["authorization"] == "Bearer nous-abc"
    finally:
        p.close()


def test_base_url_override():
    """Allow pointing at a staging/dev portal."""
    p = NousProvider(
        api_key="k",
        base_url="https://staging.nousresearch.test/v1",
    )
    try:
        assert p.base_url == "https://staging.nousresearch.test/v1"
    finally:
        p.close()
