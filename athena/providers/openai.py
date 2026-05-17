"""OpenAI provider — Chat Completions API at api.openai.com.

Defaults to ``/chat/completions`` since that's what the rest of the
ecosystem speaks. ``/responses`` is a Phase-9 follow-on if needed.

The streaming protocol is SSE: ``data: <json>\\n\\n`` with one
``choices[0].delta`` per chunk. Tool calls arrive as a sequence of
incremental deltas with ``index`` discriminating concurrent calls; the
parser accumulates ``function.name`` (string) and ``function.arguments``
(string fragment) per index and emits one ``StreamChunk("tool_call")``
per index when the stream ends.

Used as the base for OpenAI-compat / OpenRouter / Nous in Prompt 8.4.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from . import register_provider
from .base import Provider, StreamChunk


_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _raise_with_body(response: httpx.Response) -> None:
    """Read the streaming response body before raising so the error
    surfaces the API's own complaint (model not found, key invalid,
    quota exhausted, etc.) instead of just the URL and status code.
    """
    if response.status_code < 400:
        return
    try:
        response.read()
        body = (response.text or "").strip()
    except Exception:
        body = ""
    raise httpx.HTTPStatusError(
        f"{response.status_code} from {response.request.url}: {body[:800]}",
        request=response.request,
        response=response,
    )


class OpenAICompatibleProvider(Provider):
    """Shared base for OpenAI + every OpenAI-compatible service. Subclasses
    set ``name`` and may override ``base_url`` / extra request headers.
    """
    name = ""
    requires_api_key = True

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 600.0,
        extra_headers: dict[str, str] | None = None,
        **kwargs: Any,
    ):
        super().__init__(api_key=api_key, **kwargs)
        self.base_url = (base_url or self._default_base_url()).rstrip("/")
        headers: dict[str, str] = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        if extra_headers:
            headers.update(extra_headers)
        self._client = httpx.Client(
            base_url=self.base_url, headers=headers, timeout=timeout
        )

    def _default_base_url(self) -> str:
        return _DEFAULT_BASE_URL

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
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "stream_options": {"include_usage": True},
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools

        with self._client.stream(
            "POST", "/chat/completions", json=payload
        ) as r:
            _raise_with_body(r)
            yield from self._parse_sse(r)

    def parse_tool_calls(
        self, content: str, raw_response: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        return content, []

    # ---- Discovery ----

    def list_models(self) -> list[str]:
        """``GET /v1/models`` per OpenAI's spec — returns
        ``{"object":"list","data":[{"id":..., ...}, ...]}``. Inherited
        by every OpenAI-compatible subclass (OpenAI, openai_compat,
        OpenRouter, Nous); their endpoints all return the same shape."""
        r = self._client.get("/models")
        r.raise_for_status()
        data = r.json() or {}
        items = data.get("data") or []
        return [
            item["id"] for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    # ---- Internals ----

    def _parse_sse(self, response: httpx.Response) -> Iterator[StreamChunk]:
        """Parse OpenAI-style SSE into StreamChunks.

        Tool-call assembly is index-keyed: each delta carries a
        ``tool_calls`` array where each entry has an ``index`` and
        partial ``function.name`` / ``function.arguments`` fragments.
        We accumulate per index and flush on stream end.
        """
        partial_tools: dict[int, dict[str, Any]] = {}
        usage: dict[str, int] | None = None
        finish_reason = "stop"

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
            choices = event.get("choices") or []
            for ch in choices:
                delta = ch.get("delta") or {}
                # Content delta.
                text = delta.get("content")
                if text:
                    yield StreamChunk("content", text)
                # Tool-call deltas.
                for tc in delta.get("tool_calls") or []:
                    idx = int(tc.get("index", 0))
                    bucket = partial_tools.setdefault(idx, {
                        "name": "",
                        "args": "",
                        "id": tc.get("id", ""),
                    })
                    if tc.get("id") and not bucket["id"]:
                        bucket["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if "name" in fn and fn["name"]:
                        bucket["name"] += fn["name"]
                    if "arguments" in fn and fn["arguments"]:
                        bucket["args"] += fn["arguments"]
                if ch.get("finish_reason"):
                    finish_reason = ch["finish_reason"]
            # Usage block is on the final event with empty choices.
            u = event.get("usage") or {}
            if u:
                usage = {
                    "prompt_tokens": int(u.get("prompt_tokens", 0) or 0),
                    "completion_tokens": int(u.get("completion_tokens", 0) or 0),
                }

        # Emit accumulated tool calls.
        for idx in sorted(partial_tools):
            tool = partial_tools[idx]
            args_raw = tool["args"]
            try:
                args = json.loads(args_raw) if args_raw else {}
            except json.JSONDecodeError:
                args = {"_raw": args_raw}
            yield StreamChunk("tool_call", {
                "name": tool["name"],
                "arguments": args,
                "id": tool["id"],
            })

        yield StreamChunk("usage", usage or {"prompt_tokens": 0, "completion_tokens": 0})
        yield StreamChunk("end", {"reason": finish_reason})


@register_provider
class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
