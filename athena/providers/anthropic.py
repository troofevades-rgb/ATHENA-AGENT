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

import itertools
import json
from collections.abc import Iterator
from typing import Any

_synth_counter = itertools.count(1)


def _synth_tool_id() -> str:
    """Synthesize a tool_use id when the upstream message log didn't
    carry one. Anthropic requires every ``tool_result`` block to
    reference a ``tool_use_id`` matching some preceding ``tool_use``.
    The translator pairs synthesized ids between adjacent
    assistant/tool turns; each one needs to be unique within a request.
    """
    return f"toolu_athena_{next(_synth_counter):08d}"


import httpx

from . import register_provider
from .base import Provider, StreamChunk

_DEFAULT_VERSION = "2023-06-01"
_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"


def _raise_with_body(response: httpx.Response) -> None:
    """Like ``response.raise_for_status()`` but reads the response body
    first so the error message includes the API's own explanation. For
    a streaming response the body is otherwise lost.
    """
    if response.status_code < 400:
        return
    try:
        response.read()
        body = (response.text or "").strip()
    except Exception:
        body = ""
    snippet = body[:800]
    raise httpx.HTTPStatusError(
        f"{response.status_code} from {response.request.url}: {snippet}",
        request=response.request,
        response=response,
    )


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
        body_messages = self._translate_messages(body_messages)
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
            _raise_with_body(r)
            yield from self._parse_sse(r)

    def parse_tool_calls(
        self, content: str, raw_response: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Delegate to the parser registry — Phase 9. Routes on
        ``raw_response.model`` if present so per-model entries (e.g.
        Claude 4 vs Claude 3) can specialize. Falls through to the
        anthropic ``claude-*`` parser when the model field is absent."""
        from .parsers import resolve_parser

        model = ""
        if isinstance(raw_response, dict):
            m = raw_response.get("model")
            if isinstance(m, str):
                model = m
        parser = resolve_parser(self.name, model or "claude-")
        return parser(content, raw_response)

    # ---- Discovery ----

    def list_models(self) -> list[str]:
        """Return every model id the API key has access to.

        Anthropic exposes ``GET /v1/models`` returning
        ``{"data": [{"id": ..., "type": "model", ...}], "has_more": bool}``.
        We request a high limit (1000 is the documented max) and ignore
        ``has_more`` since real key catalogs are well under that.

        Note: not every Anthropic key has /models access; some are scoped
        to /messages only. The error body comes through via _raise_with_
        body so a 401 / 403 surfaces the API's explanation.
        """
        r = self._client.get("/models", params={"limit": 1000})
        _raise_with_body(r)
        data = r.json() or {}
        items = data.get("data") or []
        return [
            item["id"]
            for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]

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
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            return str(content), list(messages[1:])
        return "", list(messages)

    @staticmethod
    def _translate_messages(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert athena's Ollama-shaped message log to Anthropic's
        content-block format.

        Athena (and Ollama) speak:

          {"role": "assistant", "content": "...",
           "tool_calls": [{"id": .., "function": {"name": .., "arguments": ..}}]}
          {"role": "tool", "tool_call_id": .., "name": .., "content": ".."}

        Anthropic requires:

          {"role": "assistant",
           "content": [{"type": "text", "text": ".."},
                       {"type": "tool_use", "id": .., "name": .., "input": {..}}]}
          {"role": "user",
           "content": [{"type": "tool_result", "tool_use_id": .., "content": ".."}]}

        Adjacent tool-result messages collapse into a single user
        message (Anthropic requires alternating user/assistant turns).
        """
        out: list[dict[str, Any]] = []
        i = 0
        # Queue of ids minted for the most recent assistant turn's
        # tool_use blocks. The following tool-result turns dequeue
        # from here when their own tool_call_id is missing, so a paired
        # call+result that both lack ids still gets matching synth ids.
        pending_synth_ids: list[str] = []
        while i < len(messages):
            msg = messages[i]
            role = msg.get("role")
            content = msg.get("content") or ""

            if role == "assistant":
                blocks: list[dict[str, Any]] = []
                pending_synth_ids = []
                if isinstance(content, str) and content:
                    blocks.append({"type": "text", "text": content})
                elif isinstance(content, list):
                    # Drop empty/placeholder text blocks here too — the
                    # constraint "text blocks must be non-empty" applies
                    # whether the empty text arrived from us or from a
                    # plugin that produced ``{"type": "text", "text": ""}``.
                    for b in content:
                        if (
                            isinstance(b, dict)
                            and b.get("type") == "text"
                            and not (b.get("text") or "").strip()
                        ):
                            continue
                        blocks.append(b)
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args) if args.strip() else {}
                        except json.JSONDecodeError:
                            args = {"_raw": args}
                    tc_id = tc.get("id")
                    if not tc_id:
                        tc_id = _synth_tool_id()
                        pending_synth_ids.append(tc_id)
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc_id,
                            "name": fn.get("name", ""),
                            "input": args if isinstance(args, dict) else {},
                        }
                    )
                # If the turn would have zero blocks (no text, no tool
                # calls — happens on mid-stream interrupt or aggressive
                # plugin filtering), drop it entirely. Anthropic rejects
                # both empty content arrays and empty text blocks, and
                # there's nothing useful in a content-less assistant turn
                # for the model to see anyway.
                if not blocks:
                    i += 1
                    continue
                out.append({"role": "assistant", "content": blocks})
                i += 1
                continue

            if role == "tool":
                # Coalesce consecutive tool results into one user message.
                results: list[dict[str, Any]] = []
                while i < len(messages) and messages[i].get("role") == "tool":
                    t = messages[i]
                    tc_id = t.get("tool_call_id")
                    if not tc_id:
                        # Pair with the next synth id minted for the
                        # preceding assistant turn.
                        tc_id = pending_synth_ids.pop(0) if pending_synth_ids else _synth_tool_id()
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tc_id,
                            "content": str(t.get("content") or ""),
                        }
                    )
                    i += 1
                out.append({"role": "user", "content": results})
                continue

            # user / system / anything else passes through with content
            # left as-is (string or already-structured blocks).
            out.append(
                {
                    "role": role or "user",
                    "content": content,
                }
            )
            i += 1
        return out

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
                out.append(
                    {
                        "name": fn.get("name", ""),
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {}) or {},
                    }
                )
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
            data = raw[len("data: ") :].strip()
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
                    yield StreamChunk(
                        "tool_call",
                        {
                            "name": tool["name"],
                            "arguments": args,
                            "id": tool["id"],
                        },
                    )
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
