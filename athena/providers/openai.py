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

import contextlib
import json
import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx

from . import register_provider
from .base import Capabilities, Provider, StreamChunk
from .rate_limit_tracker import RateLimitTracker
from .retry_utils import with_retry

_rl_logger = logging.getLogger(__name__)

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
        self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)
        # T2-02: per-credential rate-limit state for the 12-header
        # generic schema. All OpenAI-compat subclasses (OpenAIProvider,
        # OpenRouterProvider, NousProvider, OpenAICompatProvider)
        # inherit this and share the same throttle behaviour.
        self._rate_limit_state: dict[str, RateLimitTracker] = {}
        self.rate_limit_throttle_threshold: float = 0.95
        # T2-03: retry budget. Defaults match the Config defaults.
        self._retry_max: int = 5
        self._retry_backoff_s: float = 30.0
        # T2-03.9: per-session retry / abort counters for /status.
        self._retry_count: int = 0
        self._abort_count: int = 0

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

        # T2-03: retry-wrap the POST + raise-for-status +
        # rate-limit-capture step. Streaming body is outside the retry
        # boundary (we can't replay yielded chunks).
        outer_stack = contextlib.ExitStack()
        try:

            def _open_response() -> Any:
                self._maybe_throttle()
                tmp_stack = contextlib.ExitStack()
                try:
                    r = tmp_stack.enter_context(
                        self._client.stream("POST", "/chat/completions", json=payload)
                    )
                    _raise_with_body(r)
                    self._capture_rate_limit_headers(r.headers)
                except BaseException:
                    tmp_stack.close()
                    raise
                outer_stack.push(tmp_stack.pop_all())
                return r

            response = with_retry(
                _open_response,
                max_retries=self._retry_max,
                max_backoff_s=self._retry_backoff_s,
                on_retry=lambda _c: self._inc_retry(),
                on_abort=lambda _c: self._inc_abort(),
                provider_label=self.name,
            )
            yield from self._parse_sse(response)
        finally:
            outer_stack.close()

    def _inc_retry(self) -> None:
        self._retry_count += 1

    def _inc_abort(self) -> None:
        self._abort_count += 1

    def get_retry_counts(self) -> dict[str, int]:
        """Per-session retry / abort counters (T2-03.9)."""
        return {"retries": self._retry_count, "aborts": self._abort_count}

    # ---- T2-02: rate-limit hooks shared across every OpenAI-compat subclass ----

    def _maybe_throttle(self) -> None:
        cred_id = self._current_credential_id()
        tracker = self._rate_limit_state.get(cred_id)
        if tracker is None:
            return
        if not tracker.should_throttle(threshold=self.rate_limit_throttle_threshold):
            return
        sleep_s = tracker.throttle_seconds(threshold=self.rate_limit_throttle_threshold)
        if sleep_s <= 0:
            return
        _rl_logger.info(
            "%s preemptive throttle: sleeping %.1fs (%s)",
            self.name,
            sleep_s,
            tracker.format(),
        )
        time.sleep(sleep_s)

    def _capture_rate_limit_headers(self, headers: Any) -> None:
        tracker = RateLimitTracker.from_headers(headers, provider=self.name, schema="generic")
        if tracker is None:
            return
        self._rate_limit_state[self._current_credential_id()] = tracker

    def _current_credential_id(self) -> str:
        api_key = getattr(self, "api_key", None) or ""
        if api_key:
            return f"...{api_key[-4:]}"
        return "default"

    def get_rate_limit_state(self) -> dict[str, RateLimitTracker]:
        """Return the latest rate-limit tracker per credential (T2-02)."""
        return dict(self._rate_limit_state)

    def parse_tool_calls(
        self, content: str, raw_response: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Delegate to the parser registry — Phase 9. Per-model entries
        (legacy gpt-3.5/gpt-4-0613 use function_call; everything else
        uses tool_calls; gpt-oss-* uses harmony channels) get tried
        first, then the provider-default."""
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
        """``GET /v1/models`` per OpenAI's spec — returns
        ``{"object":"list","data":[{"id":..., ...}, ...]}``. Inherited
        by every OpenAI-compatible subclass (OpenAI, openai_compat,
        OpenRouter, Nous); their endpoints all return the same shape."""
        r = self._client.get("/models")
        _raise_with_body(r)
        data = r.json() or {}
        items = data.get("data") or []
        return [
            item["id"]
            for item in items
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
            data = raw[len("data: ") :].strip()
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
                    bucket = partial_tools.setdefault(
                        idx,
                        {
                            "name": "",
                            "args": "",
                            "id": tc.get("id", ""),
                        },
                    )
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
            yield StreamChunk(
                "tool_call",
                {
                    "name": tool["name"],
                    "arguments": args,
                    "id": tool["id"],
                },
            )

        yield StreamChunk("usage", usage or {"prompt_tokens": 0, "completion_tokens": 0})
        yield StreamChunk("end", {"reason": finish_reason})


@register_provider
class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        """GPT-4o family: vision, embeddings (separate endpoint),
        prompt caching (automatic since 2024-10), structured output
        (JSON / strict schema), 128k context."""
        return Capabilities(
            tool_calls=True,
            streaming=True,
            vision=True,
            max_image_edge_px=2048,
            prompt_caching=True,
            cache_ttls_seconds=(),  # OpenAI cache TTL is implicit ~5min
            structured_output=True,
            embeddings=True,
            max_context_tokens=128_000,
            is_local=False,
            native_format="openai",
        )
