"""OllamaProvider — stream_chat parses /api/chat NDJSON into StreamChunks."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from athena.providers import get_provider_class
from athena.providers.ollama import OllamaProvider


def _ndjson(*objs: dict) -> bytes:
    return b"\n".join(json.dumps(o).encode("utf-8") for o in objs) + b"\n"


@pytest.fixture
def provider():
    p = OllamaProvider(host="http://test-host.invalid:11434")
    yield p
    p.close()


def test_registered_under_name_ollama():
    """Importing athena.providers.ollama side-effects the registry."""
    assert get_provider_class("ollama") is OllamaProvider


def test_stream_chat_yields_content_chunks(provider: OllamaProvider):
    sample = _ndjson(
        {"message": {"role": "assistant", "content": "Hello "}, "done": False},
        {"message": {"role": "assistant", "content": "world."}, "done": False},
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 8,
            "eval_count": 2,
            "eval_duration": 1_000_000,
        },
    )
    with respx.mock(assert_all_called=False) as m:
        m.post("http://test-host.invalid:11434/api/chat").mock(
            return_value=httpx.Response(200, content=sample)
        )
        chunks = list(provider.stream_chat(model="qwen", messages=[]))
    kinds = [c.kind for c in chunks]
    assert "content" in kinds
    assert kinds[-1] == "end"
    contents = [c.payload for c in chunks if c.kind == "content"]
    assert "".join(contents) == "Hello world."


def test_stream_chat_yields_usage_with_ollama_extras(provider: OllamaProvider):
    sample = _ndjson(
        {"message": {"role": "assistant", "content": "hi"}, "done": False},
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 42,
            "eval_count": 7,
            "eval_duration": 5_000_000_000,
        },
    )
    with respx.mock() as m:
        m.post("http://test-host.invalid:11434/api/chat").mock(
            return_value=httpx.Response(200, content=sample)
        )
        chunks = list(provider.stream_chat(model="qwen", messages=[]))
    usage = next(c for c in chunks if c.kind == "usage")
    assert usage.payload["prompt_tokens"] == 42
    assert usage.payload["completion_tokens"] == 7
    # Ollama-specific extras the agent's stream_stats footer needs:
    assert usage.payload["prompt_eval_count"] == 42
    assert usage.payload["eval_count"] == 7
    assert usage.payload["eval_duration"] == 5_000_000_000


def test_stream_chat_yields_tool_call_chunks(provider: OllamaProvider):
    sample = _ndjson(
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "Read", "arguments": {"file_path": "/tmp/x"}}}
                ],
            },
            "done": False,
        },
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "tool_calls",
            "prompt_eval_count": 5,
            "eval_count": 3,
        },
    )
    with respx.mock() as m:
        m.post("http://test-host.invalid:11434/api/chat").mock(
            return_value=httpx.Response(200, content=sample)
        )
        chunks = list(provider.stream_chat(model="qwen", messages=[]))
    tool_chunks = [c for c in chunks if c.kind == "tool_call"]
    assert len(tool_chunks) == 1
    payload = tool_chunks[0].payload
    assert payload["name"] == "Read"
    assert payload["arguments"] == {"file_path": "/tmp/x"}


def test_stream_chat_passes_num_ctx_and_temperature(provider: OllamaProvider):
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_ndjson(
                {"message": {"content": ""}, "done": True, "prompt_eval_count": 1, "eval_count": 1},
            ),
        )

    with respx.mock() as m:
        m.post("http://test-host.invalid:11434/api/chat").mock(side_effect=_record)
        list(
            provider.stream_chat(
                model="qwen",
                messages=[],
                temperature=0.3,
                num_ctx=8192,
            )
        )
    body = captured["body"]
    assert body["model"] == "qwen"
    assert body["stream"] is True
    assert body["options"]["temperature"] == 0.3
    assert body["options"]["num_ctx"] == 8192


def test_stream_chat_omits_num_ctx_when_unset(provider: OllamaProvider):
    """Don't send num_ctx=0; let Ollama use its default."""
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_ndjson(
                {"message": {"content": ""}, "done": True, "prompt_eval_count": 1, "eval_count": 1},
            ),
        )

    with respx.mock() as m:
        m.post("http://test-host.invalid:11434/api/chat").mock(side_effect=_record)
        list(provider.stream_chat(model="qwen", messages=[]))
    assert "num_ctx" not in captured["body"]["options"]


def test_stream_chat_passes_tools_when_provided(provider: OllamaProvider):
    captured: dict = {}

    def _record(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_ndjson(
                {"message": {"content": ""}, "done": True, "prompt_eval_count": 1, "eval_count": 1},
            ),
        )

    tools = [
        {
            "type": "function",
            "function": {"name": "Read", "description": "x", "parameters": {}},
        }
    ]
    with respx.mock() as m:
        m.post("http://test-host.invalid:11434/api/chat").mock(side_effect=_record)
        list(provider.stream_chat(model="qwen", messages=[], tools=tools))
    assert captured["body"]["tools"] == tools


def test_show_model_returns_metadata_dict(provider: OllamaProvider):
    with respx.mock() as m:
        m.post("http://test-host.invalid:11434/api/show").mock(
            return_value=httpx.Response(
                200, json={"modelfile": "FROM qwen", "system": "be terse", "details": {}}
            )
        )
        data = provider.show_model("qwen")
    assert data["system"] == "be terse"


def test_list_models_returns_names(provider: OllamaProvider):
    with respx.mock() as m:
        m.get("http://test-host.invalid:11434/api/tags").mock(
            return_value=httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "qwen2.5-coder:14b"},
                        {"name": "llama3.1:8b"},
                    ]
                },
            )
        )
        names = provider.list_models()
    assert names == ["qwen2.5-coder:14b", "llama3.1:8b"]


def test_host_stripped_of_trailing_slash():
    """OllamaProvider should normalize the host so request paths don't double-slash."""
    p = OllamaProvider(host="http://x.example:11434/")
    try:
        assert p.host == "http://x.example:11434"
    finally:
        p.close()


def test_count_tokens_default_heuristic(provider: OllamaProvider):
    """Inherited from base — sanity check it still works on the provider."""
    assert provider.count_tokens("hello world today") == 4


def test_close_is_idempotent(provider: OllamaProvider):
    provider.close()
    provider.close()  # no exception


def test_parse_tool_calls_returns_unchanged_for_now():
    """Phase 9 will plug in per-model content recovery; Phase 8's default
    leaves the content alone (native tool_calls were extracted during streaming)."""
    p = OllamaProvider()
    out, calls = p.parse_tool_calls("some content", {"model": "qwen"})
    assert out == "some content"
    assert calls == []
    p.close()
