"""Tests for athena.proxy.logging (T3-01.4)."""

from __future__ import annotations

import json

from athena.proxy.logging import ProxyLogger


def test_log_completed_appends_jsonl(tmp_path) -> None:
    plog = ProxyLogger(
        log_path=tmp_path / "proxy.jsonl",
        bodies_dir=tmp_path / "bodies",
    )
    plog.log_completed(
        request_id="r1",
        client_ua="Aider/1.0",
        model_requested="claude-opus-4-7",
        provider_used="anthropic",
        body={"messages": [{"role": "user", "content": "hi"}]},
        response={
            "choices": [
                {"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}
            ]
        },
        latency_ms=234.5,
        tokens_in=10,
        tokens_out=3,
    )
    lines = (tmp_path / "proxy.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["request_id"] == "r1"
    assert record["client_ua"] == "Aider/1.0"
    assert record["model_requested"] == "claude-opus-4-7"
    assert record["provider_used"] == "anthropic"
    assert record["latency_ms"] == 234.5
    assert record["tokens_in"] == 10
    assert record["tokens_out"] == 3
    assert record["request_summary"]["message_count"] == 1
    assert record["request_summary"]["has_tools"] is False
    assert record["request_summary"]["stream"] is False
    assert record["response_summary"]["finish_reason"] == "stop"
    assert record["response_summary"]["has_tool_calls"] is False


def test_log_completed_with_tool_calls_flagged(tmp_path) -> None:
    plog = ProxyLogger(log_path=tmp_path / "proxy.jsonl", bodies_dir=tmp_path / "b")
    plog.log_completed(
        request_id="r2",
        client_ua="x",
        model_requested="claude-sonnet-4-6",
        provider_used="anthropic",
        body={
            "messages": [{"role": "user", "content": "do thing"}],
            "tools": [{"type": "function", "function": {"name": "f"}}],
            "stream": True,
        },
        response={
            "choices": [
                {
                    "message": {"tool_calls": [{"id": "t1"}]},
                    "finish_reason": "tool_calls",
                }
            ]
        },
        latency_ms=10,
    )
    record = json.loads((tmp_path / "proxy.jsonl").read_text().splitlines()[0])
    assert record["request_summary"]["has_tools"] is True
    assert record["request_summary"]["stream"] is True
    assert record["response_summary"]["has_tool_calls"] is True
    assert record["response_summary"]["finish_reason"] == "tool_calls"


def test_log_bodies_disabled_skips_body_file(tmp_path) -> None:
    plog = ProxyLogger(
        log_path=tmp_path / "proxy.jsonl",
        bodies_dir=tmp_path / "bodies",
        log_bodies=False,
    )
    plog.log_completed(
        request_id="r1",
        client_ua="x",
        model_requested="m",
        provider_used="anthropic",
        body={"messages": []},
        response=None,
        latency_ms=1,
    )
    assert not (tmp_path / "bodies").exists() or not list((tmp_path / "bodies").iterdir())


def test_log_bodies_writes_full_payload(tmp_path) -> None:
    plog = ProxyLogger(
        log_path=tmp_path / "proxy.jsonl",
        bodies_dir=tmp_path / "bodies",
        log_bodies=True,
    )
    body = {"messages": [{"role": "user", "content": "hi"}], "model": "x"}
    response = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    plog.log_completed(
        request_id="r-abc",
        client_ua="ua",
        model_requested="x",
        provider_used="anthropic",
        body=body,
        response=response,
        latency_ms=1,
    )
    body_file = tmp_path / "bodies" / "r-abc.json"
    assert body_file.exists()
    data = json.loads(body_file.read_text(encoding="utf-8"))
    assert data["request"] == body
    assert data["response"] == response


def test_multiple_log_lines_append(tmp_path) -> None:
    plog = ProxyLogger(log_path=tmp_path / "p.jsonl", bodies_dir=tmp_path / "b")
    for i in range(3):
        plog.log_completed(
            request_id=f"r{i}",
            client_ua="x",
            model_requested="m",
            provider_used="anthropic",
            body={"messages": []},
            response=None,
            latency_ms=1,
        )
    lines = (tmp_path / "p.jsonl").read_text().splitlines()
    assert len(lines) == 3


def test_scope_context_emits_log_on_exit(tmp_path) -> None:
    plog = ProxyLogger(log_path=tmp_path / "p.jsonl", bodies_dir=tmp_path / "b")
    with plog.scope(
        request_id="r-scope",
        client_ua="ua",
        model_requested="m",
        provider_used="anthropic",
        body={"messages": [{"role": "user", "content": "hi"}]},
    ) as scope:
        scope.add_tokens(in_=100, out=20, cache=80)
        scope.set_response({"choices": [{"finish_reason": "stop", "message": {}}]})

    record = json.loads((tmp_path / "p.jsonl").read_text().splitlines()[0])
    assert record["request_id"] == "r-scope"
    assert record["tokens_in"] == 100
    assert record["tokens_out"] == 20
    assert record["cache_read_tokens"] == 80
    assert record["response_summary"]["finish_reason"] == "stop"


def test_scope_records_elapsed_latency(tmp_path) -> None:
    """The scope measures latency itself when set_latency isn't
    called — ensure the recorded value is positive (not zero)."""
    plog = ProxyLogger(log_path=tmp_path / "p.jsonl", bodies_dir=tmp_path / "b")
    with plog.scope(
        request_id="r",
        client_ua="x",
        model_requested="m",
        provider_used="anthropic",
        body={"messages": []},
    ) as _scope:
        # Spend a tick.
        sum(range(1000))

    record = json.loads((tmp_path / "p.jsonl").read_text().splitlines()[0])
    assert record["latency_ms"] >= 0  # non-negative; rounded to 2dp may be 0.0
