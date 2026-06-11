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


def test_stream_chat_skips_malformed_ndjson_line(provider: OllamaProvider):
    """Regression: a malformed NDJSON line (truncated frame, proxy
    keepalive, etc.) used to raise json.JSONDecodeError out of the
    generator and crash the whole turn. It must now be skipped, and the
    surrounding valid frames still parse."""
    body = (
        json.dumps({"message": {"content": "Hello "}, "done": False}).encode("utf-8")
        + b"\n"
        + b"this is not json{{{\n"  # malformed line in the middle
        + json.dumps({"message": {"content": "world."}, "done": False}).encode("utf-8")
        + b"\n"
        + json.dumps(
            {"message": {"content": ""}, "done": True, "prompt_eval_count": 1, "eval_count": 2}
        ).encode("utf-8")
        + b"\n"
    )
    with respx.mock(assert_all_called=False) as m:
        m.post("http://test-host.invalid:11434/api/chat").mock(
            return_value=httpx.Response(200, content=body)
        )
        chunks = list(provider.stream_chat(model="qwen", messages=[]))
    contents = [c.payload for c in chunks if c.kind == "content"]
    assert "".join(contents) == "Hello world."
    assert chunks[-1].kind == "end"


def test_stream_chat_surfaces_in_band_error_frame(provider: OllamaProvider):
    """An in-band {"error": ...} frame (CUDA OOM, model-runner crash)
    inside a 200 stream must surface as a provider error, not be
    silently swallowed into a blank turn."""
    body = (
        json.dumps({"message": {"content": "partial"}, "done": False}).encode("utf-8")
        + b"\n"
        + json.dumps({"error": "CUDA out of memory"}).encode("utf-8")
        + b"\n"
    )
    with respx.mock(assert_all_called=False) as m:
        m.post("http://test-host.invalid:11434/api/chat").mock(
            return_value=httpx.Response(200, content=body)
        )
        with pytest.raises(RuntimeError, match="CUDA out of memory"):
            list(provider.stream_chat(model="qwen", messages=[]))


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


def test_stream_chat_passes_parseltongue_options(provider: OllamaProvider):
    """The full parseltongue option surface — top_p, top_k, repeat_penalty,
    mirostat*, seed, stop — must end up inside ``options`` so the policy
    layer's params actually reach the model rather than getting silently
    dropped on the way through."""
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
                temperature=0.2,
                top_p=0.85,
                top_k=42,
                repeat_penalty=1.07,
                mirostat=2,
                mirostat_tau=4.5,
                mirostat_eta=0.15,
                seed=1234,
                stop=["</tool_call>"],
            )
        )
    opts = captured["body"]["options"]
    assert opts["temperature"] == 0.2
    assert opts["top_p"] == 0.85
    assert opts["top_k"] == 42
    assert opts["repeat_penalty"] == 1.07
    assert opts["mirostat"] == 2
    assert opts["mirostat_tau"] == 4.5
    assert opts["mirostat_eta"] == 0.15
    assert opts["seed"] == 1234
    assert opts["stop"] == ["</tool_call>"]


def test_stream_chat_drops_unknown_options(provider: OllamaProvider):
    """A kwarg the Ollama API doesn't recognize must NOT be smuggled
    into the request body — that would either confuse the server or
    silently no-op. Filter to the known option set."""
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
                top_p=0.9,
                completely_made_up_param="oops",
            )
        )
    opts = captured["body"]["options"]
    assert opts["top_p"] == 0.9
    assert "completely_made_up_param" not in opts


def test_stream_chat_omits_none_valued_options(provider: OllamaProvider):
    """A policy that explicitly passes ``None`` for a param (meaning
    'don't override, use Ollama's default') shouldn't send the key
    at all."""
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
        list(provider.stream_chat(model="qwen", messages=[], top_p=None, top_k=40))
    opts = captured["body"]["options"]
    assert "top_p" not in opts
    assert opts["top_k"] == 40


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


def test_connect_timeout_bounded_while_read_stays_generous():
    """Connect must fail fast (so an unreachable host can't hang launch),
    but the read/write budget stays large for long generations."""
    p = OllamaProvider(host="http://x.invalid:11434", timeout=600.0, connect_timeout=10.0)
    try:
        assert p._client.timeout.connect == 10.0
        assert p._client.timeout.read == 600.0
        assert p._client.timeout.write == 600.0
    finally:
        p.close()


def test_connect_timeout_clamped_to_total_timeout():
    """A custom timeout smaller than the connect default still behaves —
    connect can't exceed the overall budget."""
    p = OllamaProvider(host="http://x.invalid:11434", timeout=2.0, connect_timeout=10.0)
    try:
        assert p._client.timeout.connect == 2.0
        assert p._probe_timeout == 2.0
    finally:
        p.close()


def test_metadata_probes_use_short_timeout(provider: OllamaProvider):
    """list_models / show_model must pass the short probe timeout
    per-request, NOT inherit the 600s generation read timeout — that was
    the launch-brick: the startup reachability probe could hang 10 min
    on a blackholed host."""
    captured: dict[str, object] = {}

    class _StubClient:
        def get(self, url, **kwargs):
            captured["get_timeout"] = kwargs.get("timeout")
            return httpx.Response(
                200, json={"models": [{"name": "m"}]}, request=httpx.Request("GET", url)
            )

        def post(self, url, **kwargs):
            captured["post_timeout"] = kwargs.get("timeout")
            return httpx.Response(200, json={"system": "s"}, request=httpx.Request("POST", url))

    provider._client = _StubClient()  # type: ignore[assignment]
    provider.list_models()
    provider.show_model("m")

    assert captured["get_timeout"] == provider._probe_timeout
    assert captured["post_timeout"] == provider._probe_timeout
    assert provider._probe_timeout < 600.0


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


# ---------------------------------------------------------------------------
# T2-08 hotfix: 404 carries Ollama's "model not found" message
# ---------------------------------------------------------------------------


def test_404_model_not_found_message_surfaces(provider: OllamaProvider):
    """When Ollama returns 404 with its standard
    {"error": "model 'foo' not found, try pulling it first"} body,
    the HTTPStatusError message includes that human-readable text
    instead of the generic 404 line."""
    import json

    import httpx
    import respx

    from athena.providers.retry_utils import RetryBudgetExceeded

    provider._retry_max = 0  # don't retry; we want the underlying error
    body = json.dumps(
        {"error": "model 'qwen2.5-coder:14b' not found, try pulling it first"}
    ).encode("utf-8")
    with respx.mock() as m:
        m.post("http://test-host.invalid:11434/api/chat").mock(
            return_value=httpx.Response(404, content=body)
        )
        try:
            list(
                provider.stream_chat(
                    model="qwen2.5-coder:14b",
                    messages=[{"role": "user", "content": "x"}],
                )
            )
            raise AssertionError("expected an HTTPStatusError / RetryBudgetExceeded")
        except (httpx.HTTPStatusError, RetryBudgetExceeded) as e:
            assert "model 'qwen2.5-coder:14b' not found" in str(e)
            assert "try pulling it first" in str(e)


def test_500_unwraps_error_field_when_present(provider: OllamaProvider):
    """Same unwrap logic applies to other 4xx/5xx with the same
    Ollama error envelope shape."""
    import httpx
    import respx

    from athena.providers.retry_utils import RetryBudgetExceeded

    provider._retry_max = 0
    body = b'{"error": "internal CUDA OOM, retry with smaller batch"}'
    with respx.mock() as m:
        m.post("http://test-host.invalid:11434/api/chat").mock(
            return_value=httpx.Response(500, content=body)
        )
        try:
            list(provider.stream_chat(model="x", messages=[{"role": "user", "content": "y"}]))
            raise AssertionError("expected HTTPStatusError / RetryBudgetExceeded")
        except (httpx.HTTPStatusError, RetryBudgetExceeded) as e:
            assert "internal CUDA OOM" in str(e)


def test_404_with_non_json_body_falls_through_to_raw(provider: OllamaProvider):
    """A 404 with a non-JSON body still surfaces the raw text in the
    HTTPStatusError message (no crash on the json.loads attempt)."""
    import httpx
    import respx

    from athena.providers.retry_utils import RetryBudgetExceeded

    provider._retry_max = 0
    with respx.mock() as m:
        m.post("http://test-host.invalid:11434/api/chat").mock(
            return_value=httpx.Response(404, content=b"raw plain-text 404 body")
        )
        try:
            list(provider.stream_chat(model="x", messages=[{"role": "user", "content": "y"}]))
            raise AssertionError("expected HTTPStatusError / RetryBudgetExceeded")
        except (httpx.HTTPStatusError, RetryBudgetExceeded) as e:
            assert "raw plain-text 404 body" in str(e)
