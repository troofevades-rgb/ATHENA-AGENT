"""Ollama provider — local ``/api/chat`` backend.

Default and best-supported. The previous v1 ``athena/ollama_client.py``
moved here verbatim then adapted to yield :class:`StreamChunk` objects
instead of the v1 ``ChatChunk``. The old module is now a back-compat
shim that re-exports ``OllamaClient`` as an alias of
:class:`OllamaProvider`.

Modelfile SYSTEM inheritance: Ollama lets a custom model carry a
``SYSTEM`` directive in its Modelfile. The agent's ``_build_system``
calls :meth:`show_model` at session start (and after ``/clear`` /
``/cwd``) and prepends the result. The provider doesn't auto-inject in
``stream_chat`` — that would double the ``/api/show`` HTTP calls and
fight with the agent's prompt assembly.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from typing import Any

import httpx

from . import register_provider
from .base import Provider, StreamChunk
from .retry_utils import with_retry


@register_provider
class OllamaProvider(Provider):
    name = "ollama"
    requires_api_key = False

    def __init__(
        self,
        host: str = "http://127.0.0.1:11434",
        *,
        timeout: float = 600.0,
        **kwargs: Any,
    ):
        super().__init__(api_key=None, **kwargs)
        self.host = host.rstrip("/")
        self._client = httpx.Client(timeout=timeout)
        # T2-03: retry budget. Ollama has no credential rotation
        # (single local daemon, no API key pool), but 5xx and network
        # errors against a local daemon are typically transient
        # (daemon-not-yet-ready, port still binding) and benefit
        # from the same retry policy.
        self._retry_max: int = 5
        self._retry_backoff_s: float = 30.0

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
        """Stream a chat completion. Yields :class:`StreamChunk` chunks.

        Ollama's tool-call payloads arrive in a single chunk (not split
        across deltas like OpenAI), so each tool_call shows up whole.

        ``num_ctx`` is passed through ``kwargs`` for Ollama-specific
        context-window control; other kwargs are ignored.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools
        num_ctx = kwargs.get("num_ctx")
        if num_ctx:
            payload["options"]["num_ctx"] = num_ctx
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens

        # T2-03: retry-wrap the open-stream + raise-for-status step.
        # Streaming body itself is outside the retry boundary.
        outer_stack = contextlib.ExitStack()
        try:

            def _open_response() -> Any:
                tmp_stack = contextlib.ExitStack()
                try:
                    r = tmp_stack.enter_context(
                        self._client.stream("POST", f"{self.host}/api/chat", json=payload)
                    )
                    r.raise_for_status()
                except BaseException:
                    tmp_stack.close()
                    raise
                outer_stack.push(tmp_stack.pop_all())
                return r

            r = with_retry(
                _open_response,
                max_retries=self._retry_max,
                max_backoff_s=self._retry_backoff_s,
                provider_label=self.name,
            )
            for line in r.iter_lines():
                if not line:
                    continue
                obj = json.loads(line)
                msg = obj.get("message", {}) or {}
                content = msg.get("content") or ""
                if content:
                    yield StreamChunk("content", content)
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function", {}) or {}
                    yield StreamChunk(
                        "tool_call",
                        {
                            "name": fn.get("name", ""),
                            "arguments": fn.get("arguments", {}),
                            "id": tc.get("id", ""),
                        },
                    )
                if obj.get("done"):
                    yield StreamChunk(
                        "usage",
                        {
                            "prompt_tokens": obj.get("prompt_eval_count", 0) or 0,
                            "completion_tokens": obj.get("eval_count", 0) or 0,
                            # Ollama-specific extras the agent's stream_stats uses
                            # for the tok/s footer.
                            "prompt_eval_count": obj.get("prompt_eval_count", 0) or 0,
                            "eval_count": obj.get("eval_count", 0) or 0,
                            "eval_duration": obj.get("eval_duration", 0) or 0,
                        },
                    )
                    yield StreamChunk("end", {"reason": obj.get("done_reason", "stop")})
        finally:
            outer_stack.close()

    def parse_tool_calls(
        self, content: str, raw_response: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Delegate to the parser registry — Phase 9. Routes on
        ``raw_response.model`` so qwen* models route to qwen_xml_leakage,
        gpt-oss* models route to harmony, and the bulk of Ollama models
        fall through to the provider-default ollama_native parser."""
        from .parsers import resolve_parser

        model = ""
        if isinstance(raw_response, dict):
            m = raw_response.get("model")
            if isinstance(m, str):
                model = m
        parser = resolve_parser(self.name, model)
        return parser(content, raw_response)

    # ---- Discovery ----

    def list_models(self) -> list[str]:
        r = self._client.get(f"{self.host}/api/tags")
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]

    def show_model(self, model: str) -> dict[str, Any]:
        """Fetch model metadata via ``/api/show``.

        Returns a dict with keys like ``modelfile``, ``parameters``,
        ``template``, ``system``, ``details``. The ``system`` field is
        the Modelfile SYSTEM directive — Phase 8's agent prompt builder
        prepends it to the assembled system message.
        """
        r = self._client.post(f"{self.host}/api/show", json={"name": model})
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        return data

    # ---- Lifecycle ----

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
