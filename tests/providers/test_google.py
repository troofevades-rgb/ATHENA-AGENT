"""GoogleProvider — Gemini contents/parts shape, functionCall parts."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from athena.providers import StreamChunk, get_provider_class
from athena.providers.google import GoogleProvider


def _sse(*events: dict) -> bytes:
    return b"".join(
        b"data: " + json.dumps(e).encode("utf-8") + b"\n\n"
        for e in events
    )


@pytest.fixture
def provider():
    p = GoogleProvider(
        api_key="goog-test", base_url="https://gemini.test/v1beta",
    )
    yield p
    p.close()


def test_registered_under_name_google():
    assert get_provider_class("google") is GoogleProvider


def test_stream_chat_chunks_text_and_usage(provider):
    sample = _sse(
        {"candidates": [{"content": {"parts": [{"text": "hello "}], "role": "model"}}]},
        {"candidates": [{"content": {"parts": [{"text": "world"}], "role": "model"},
                         "finishReason": "STOP"}],
         "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 2}},
    )
    with respx.mock() as m:
        m.post(
            "https://gemini.test/v1beta/models/gemini-1.5-pro:streamGenerateContent"
        ).mock(return_value=httpx.Response(200, content=sample))
        chunks = list(provider.stream_chat(
            model="gemini-1.5-pro",
            messages=[{"role": "user", "content": "hi"}],
        ))
    contents = [c.payload for c in chunks if c.kind == "content"]
    assert "".join(contents) == "hello world"
    usage = next(c for c in chunks if c.kind == "usage")
    assert usage.payload == {"prompt_tokens": 7, "completion_tokens": 2}
    assert chunks[-1].payload["reason"] == "STOP"


def test_function_calls_parsed_as_tool_call_chunks(provider):
    sample = _sse(
        {"candidates": [{"content": {"parts": [
            {"functionCall": {"name": "Read", "args": {"path": "/tmp/x"}}}
        ], "role": "model"}, "finishReason": "STOP"}],
         "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 3}},
    )
    with respx.mock() as m:
        m.post(
            "https://gemini.test/v1beta/models/gemini-1.5-pro:streamGenerateContent"
        ).mock(return_value=httpx.Response(200, content=sample))
        chunks = list(provider.stream_chat(
            model="gemini-1.5-pro",
            messages=[{"role": "user", "content": "x"}],
        ))
    tools = [c for c in chunks if c.kind == "tool_call"]
    assert len(tools) == 1
    assert tools[0].payload["name"] == "Read"
    assert tools[0].payload["arguments"] == {"path": "/tmp/x"}


def test_system_message_hoisted_to_systemInstruction(provider):
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse(
            {"candidates": [{"content": {"parts": [{"text": ""}], "role": "model"},
                             "finishReason": "STOP"}],
             "usageMetadata": {}},
        ))

    with respx.mock() as m:
        m.post(
            "https://gemini.test/v1beta/models/gemini-1.5-pro:streamGenerateContent"
        ).mock(side_effect=_record)
        list(provider.stream_chat(
            model="gemini-1.5-pro",
            messages=[
                {"role": "system", "content": "be terse"},
                {"role": "user", "content": "hi"},
            ],
        ))
    body = captured["body"]
    assert body["systemInstruction"]["parts"][0]["text"] == "be terse"
    # System message must not appear in contents.
    roles = [c.get("role") for c in body["contents"]]
    assert "system" not in roles


def test_assistant_role_renamed_to_model(provider):
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse(
            {"candidates": [{"content": {"parts": [{"text": ""}], "role": "model"},
                             "finishReason": "STOP"}],
             "usageMetadata": {}},
        ))

    with respx.mock() as m:
        m.post(
            "https://gemini.test/v1beta/models/gemini-1.5-pro:streamGenerateContent"
        ).mock(side_effect=_record)
        list(provider.stream_chat(
            model="gemini-1.5-pro",
            messages=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hey"},
                {"role": "user", "content": "bye"},
            ],
        ))
    roles = [c.get("role") for c in captured["body"]["contents"]]
    assert roles == ["user", "model", "user"]


def test_openai_tools_converted_to_functionDeclarations(provider):
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse(
            {"candidates": [{"content": {"parts": [{"text": ""}], "role": "model"},
                             "finishReason": "STOP"}],
             "usageMetadata": {}},
        ))

    openai_tools = [{
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {}},
        },
    }]
    with respx.mock() as m:
        m.post(
            "https://gemini.test/v1beta/models/gemini-1.5-pro:streamGenerateContent"
        ).mock(side_effect=_record)
        list(provider.stream_chat(
            model="gemini-1.5-pro",
            messages=[{"role": "user", "content": "x"}],
            tools=openai_tools,
        ))
    tools_block = captured["body"]["tools"][0]
    assert "functionDeclarations" in tools_block
    decl = tools_block["functionDeclarations"][0]
    assert decl["name"] == "Read"
    assert decl["description"] == "Read a file"
    # Gemini calls them "parameters" too (one of the few places it matches).
    assert "parameters" in decl


def test_tool_role_becomes_functionResponse_part(provider):
    """tool-role messages get converted into Gemini's functionResponse parts
    under role=user — the canonical way to feed a tool result back."""
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse(
            {"candidates": [{"content": {"parts": [{"text": ""}], "role": "model"},
                             "finishReason": "STOP"}],
             "usageMetadata": {}},
        ))

    with respx.mock() as m:
        m.post(
            "https://gemini.test/v1beta/models/gemini-1.5-pro:streamGenerateContent"
        ).mock(side_effect=_record)
        list(provider.stream_chat(
            model="gemini-1.5-pro",
            messages=[
                {"role": "user", "content": "read it"},
                {"role": "tool", "name": "Read", "content": "file body"},
            ],
        ))
    contents = captured["body"]["contents"]
    # The last content entry should be a functionResponse part under user.
    last = contents[-1]
    assert last["role"] == "user"
    assert "functionResponse" in last["parts"][0]
    assert last["parts"][0]["functionResponse"]["name"] == "Read"


def test_models_prefix_stripped_from_url(provider):
    """If the caller passes 'models/gemini-...' (Gemini's canonical name
    form), strip the prefix so the URL doesn't double up."""
    called_paths: list[str] = []

    def _record(request):
        called_paths.append(request.url.path)
        return httpx.Response(200, content=_sse(
            {"candidates": [{"content": {"parts": [{"text": ""}], "role": "model"},
                             "finishReason": "STOP"}],
             "usageMetadata": {}},
        ))

    with respx.mock() as m:
        m.post(
            "https://gemini.test/v1beta/models/gemini-1.5-pro:streamGenerateContent"
        ).mock(side_effect=_record)
        list(provider.stream_chat(
            model="models/gemini-1.5-pro",
            messages=[{"role": "user", "content": "x"}],
        ))
    # Exactly one /models/ segment — not two.
    assert called_paths[0].count("/models/") == 1


def test_api_key_header_set():
    p = GoogleProvider(api_key="goog-12345")
    try:
        assert p._client.headers["x-goog-api-key"] == "goog-12345"
    finally:
        p.close()


def test_list_models_strips_models_prefix(provider):
    """Gemini's /v1beta/models returns names as "models/<id>"; strip
    the prefix so callers can pass results back to stream_chat directly."""
    with respx.mock() as m:
        m.get("https://gemini.test/v1beta/models").mock(
            return_value=httpx.Response(200, json={
                "models": [
                    {"name": "models/gemini-1.5-pro", "version": "001"},
                    {"name": "models/gemini-1.5-flash", "version": "001"},
                    {"name": "models/embedding-001", "version": "001"},
                ],
            })
        )
        names = provider.list_models()
    assert names == ["gemini-1.5-pro", "gemini-1.5-flash", "embedding-001"]


def test_list_models_propagates_error(provider):
    with respx.mock() as m:
        m.get("https://gemini.test/v1beta/models").mock(
            return_value=httpx.Response(403, json={"error": {"message": "denied"}})
        )
        with pytest.raises(httpx.HTTPStatusError):
            provider.list_models()
