"""Anthropic provider — Messages API at api.anthropic.com.

Differences from OpenAI/Ollama shape:

- ``system`` is a top-level field on the request payload, not a message
  role. The first message with ``role == "system"`` is hoisted out.
- Tools convert from the OpenAI-style
  ``{"type":"function","function":{"name","description","parameters"}}``
  to Anthropic's ``{"name","description","input_schema"}`` shape.
- Streaming is SSE (``data: <json>\\n\\n``). Tool calls arrive as a
  sequence of ``content_block_start`` (with ``type: "tool_use"``),
  ``content_block_delta`` (with ``input_json_delta``), and
  ``content_block_stop`` events — assembled into a single
  :class:`StreamChunk` of kind ``tool_call`` per tool.

API auth: ``x-api-key`` header + ``anthropic-version`` pin.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from . import register_provider
from .base import Provider, StreamChunk


_DEFAULT_VERSION = "2023-06-01"
_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"


@register_provider
class AnthropicProvider(Provider):
    name = "anthropic"
    requires_api_key = True

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        anthropic_version: str = _DEFAULT_VERSION,
        timeout: float = 600.0,
        **kwargs: Any,
    ):
        super().__init__(api_key=api_key, **kwargs)
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": anthropic_version,
                "content-type": "application/json",
            },
            timeout=timeout,
        )

    # ---- Core stream API ----

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        system, body_messages = self._split_system(messages)
        payload: dict[str, Any] = {
            "model": model,
            "messages": body_messages,
            "max_tokens": max_tokens or 4096,
            "stream": True,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = self._convert_tools(tools)

        with self._client.stream("POST", "/messages", json=payload) as r:
            r.raise_for_status()
            yield from self._parse_sse(r)

    def parse_tool_calls(
        self, content: str, raw_response: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Anthropic's tool_use blocks were already extracted during streaming.
        Phase 9 will plug content-level recovery (Anthropic XML leak) here."""
        return content, []

    # ---- Lifecycle ----

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    # ---- Internals ----

    @staticmethod
    def _split_system(
        messages: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Hoist a leading system message out of the list. Returns
        (system_text, remaining_messages). Anthropic rejects payloads
        where role=='system' appears in messages.
        """
        if not messages:
            return "", []
        first = messages[0]
        if first.get("role") == "system":
            content = first.get("content") or ""
            if isinstance(content, list):
                # join text-block list (rare for our inputs but defensive)
                content = "".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            return str(content), list(messages[1:])
        return "", list(messages)

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """OpenAI-style ``{"type":"function","function":{...}}`` →
        Anthropic-style ``{"name","description","input_schema"}``.
        Tools already in Anthropic shape pass through unchanged.
        """
        out: list[dict[str, Any]] = []
        for t in tools:
            if "function" in t and isinstance(t["function"], dict):
                fn = t["function"]
                out.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {}) or {},
                })
            else:
                # Already Anthropic shape (or unknown — pass through).
                out.append(t)
        return out

    def _parse_sse(self, response: httpx.Response) -> Iterator[StreamChunk]:
        """Decode the Anthropic streaming-events protocol into StreamChunks.

        Events of interest:
        - ``content_block_start`` with ``content_block.type == "tool_use"``:
          start accumulating a tool call (name + id).
        - ``content_block_delta`` with ``delta.type == "text_delta"``:
          emit a content chunk for ``delta.text``.
        - ``content_block_delta`` with ``delta.type == "input_json_delta"``:
          append the partial JSON to the current tool's accumulator.
        - ``content_block_stop``: if it closes a tool_use block, yield the
          assembled tool_call chunk.
        - ``message_delta``: contains usage updates and stop_reason.
        - ``message_stop``: emit the final end chunk.
        """
        # Tool calls accumulate per content-block index.
        partial_tools: dict[int, dict[str, Any]] = {}
        usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
        stop_reason = "stop"

        for raw in response.iter_lines():
            if not raw or not raw.startswith("data: "):
                continue
            data = raw[len("data: "):].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            etype = event.get("type", "")
            if etype == "content_block_start":
                block = event.get("content_block") or {}
                if block.get("type") == "tool_use":
                    idx = int(event.get("index", 0))
                    partial_tools[idx] = {
                        "name": block.get("name", ""),
                        "id": block.get("id", ""),
                        "json_acc": "",
                    }
            elif etype == "content_block_delta":
                idx = int(event.get("index", 0))
                delta = event.get("delta") or {}
                dtype = delta.get("type", "")
                if dtype == "text_delta":
                    text = delta.get("text") or ""
                    if text:
                        yield StreamChunk("content", text)
                elif dtype == "input_json_delta" and idx in partial_tools:
                    partial_tools[idx]["json_acc"] += delta.get("partial_json", "")
            elif etype == "content_block_stop":
                idx = int(event.get("index", 0))
                if idx in partial_tools:
                    tool = partial_tools.pop(idx)
                    args_raw = tool["json_acc"]
                    try:
                        args = json.loads(args_raw) if args_raw else {}
                    except json.JSONDecodeError:
                        args = {"_raw": args_raw}
                    yield StreamChunk("tool_call", {
                        "name": tool["name"],
                        "arguments": args,
                        "id": tool["id"],
                    })
            elif etype == "message_start":
                msg = event.get("message") or {}
                u = msg.get("usage") or {}
                usage["prompt_tokens"] = int(u.get("input_tokens", 0) or 0)
                usage["completion_tokens"] = int(u.get("output_tokens", 0) or 0)
            elif etype == "message_delta":
                delta = event.get("delta") or {}
                if "stop_reason" in delta:
                    stop_reason = delta["stop_reason"] or stop_reason
                u = event.get("usage") or {}
                if "output_tokens" in u:
                    usage["completion_tokens"] = int(u["output_tokens"] or 0)
            elif etype == "message_stop":
                yield StreamChunk("usage", dict(usage))
                yield StreamChunk("end", {"reason": stop_reason})
                return

        # If the stream closed without a message_stop, still emit usage + end
        # so the agent's loop terminates cleanly.
        yield StreamChunk("usage", dict(usage))
        yield StreamChunk("end", {"reason": stop_reason})
