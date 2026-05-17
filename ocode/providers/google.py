"""Google provider — Gemini API at generativelanguage.googleapis.com.

The Gemini shape is the most divergent of the three real-API providers:

- Messages → ``contents`` array of ``{"role": "user"|"model", "parts": [...]}``.
  System prompts go in a separate top-level ``system_instruction`` field
  (just text parts, no role).
- Function declarations are passed inline in the request under ``tools``
  as ``{"functionDeclarations": [...]}``.
- Streaming uses the ``streamGenerateContent?alt=sse`` endpoint and
  emits SSE events where each ``candidates[0].content.parts`` may
  contain ``text`` or ``functionCall`` entries.

Auth is via an ``x-goog-api-key`` header (or the legacy ``?key=`` query
string; we use the header).
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from . import register_provider
from .base import Provider, StreamChunk


_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


@register_provider
class GoogleProvider(Provider):
    name = "google"
    requires_api_key = True

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 600.0,
        **kwargs: Any,
    ):
        super().__init__(api_key=api_key, **kwargs)
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "x-goog-api-key": api_key,
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
        system_text, contents = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature},
        }
        if max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens
        if system_text:
            payload["systemInstruction"] = {
                "parts": [{"text": system_text}],
            }
        if tools:
            payload["tools"] = [{"functionDeclarations": self._convert_tools(tools)}]

        # Strip any "models/" prefix the caller might have included so we
        # don't end up with .../models/models/<id>.
        clean_model = model.removeprefix("models/")
        path = f"/models/{clean_model}:streamGenerateContent"
        with self._client.stream(
            "POST", path, params={"alt": "sse"}, json=payload
        ) as r:
            r.raise_for_status()
            yield from self._parse_sse(r)

    def parse_tool_calls(
        self, content: str, raw_response: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        return content, []

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    # ---- Internals ----

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Translate OpenAI/Anthropic message list to Gemini ``contents``.

        - role ``system`` → hoisted out as ``systemInstruction`` text.
        - role ``assistant`` → ``role: "model"``.
        - role ``user`` / ``tool`` → ``role: "user"`` (tool results are
          inlined as user-role function_response parts).
        """
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content")
            if role == "system":
                if isinstance(content, str):
                    system_parts.append(content)
                continue
            if role == "tool":
                # Gemini expects functionResponse parts under user role.
                contents.append({
                    "role": "user",
                    "parts": [{"functionResponse": {
                        "name": m.get("name", ""),
                        "response": {"result": str(content or "")},
                    }}],
                })
                continue
            gemini_role = "model" if role == "assistant" else "user"
            parts: list[dict[str, Any]] = []
            if isinstance(content, str) and content:
                parts.append({"text": content})
            # Native tool_calls on assistant messages become functionCall parts.
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args) if args.strip() else {}
                    except json.JSONDecodeError:
                        args = {"_raw": args}
                parts.append({"functionCall": {
                    "name": fn.get("name", ""),
                    "args": args,
                }})
            if not parts:
                parts.append({"text": ""})
            contents.append({"role": gemini_role, "parts": parts})
        return "\n\n".join(system_parts), contents

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """OpenAI-style tools → Gemini ``functionDeclarations`` entries."""
        out: list[dict[str, Any]] = []
        for t in tools:
            fn = t.get("function") if "function" in t else t
            if not isinstance(fn, dict):
                continue
            out.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}) or {},
            })
        return out

    def _parse_sse(self, response: httpx.Response) -> Iterator[StreamChunk]:
        """Parse Gemini's SSE response. Each event is a single JSON object
        whose ``candidates[0].content.parts`` contains text and/or
        functionCall entries.
        """
        usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
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
            candidates = event.get("candidates") or []
            for cand in candidates:
                content = cand.get("content") or {}
                for part in content.get("parts") or []:
                    if "text" in part and part["text"]:
                        yield StreamChunk("content", part["text"])
                    elif "functionCall" in part:
                        fc = part["functionCall"] or {}
                        yield StreamChunk("tool_call", {
                            "name": fc.get("name", ""),
                            "arguments": fc.get("args", {}) or {},
                            "id": "",
                        })
                if cand.get("finishReason"):
                    finish_reason = cand["finishReason"]
            # usageMetadata appears on the final event.
            um = event.get("usageMetadata") or {}
            if um:
                usage["prompt_tokens"] = int(um.get("promptTokenCount", 0) or 0)
                usage["completion_tokens"] = int(um.get("candidatesTokenCount", 0) or 0)

        yield StreamChunk("usage", dict(usage))
        yield StreamChunk("end", {"reason": finish_reason})
