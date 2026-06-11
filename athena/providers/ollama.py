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
import dataclasses
import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx

from . import register_provider
from .base import Capabilities, Provider, StreamChunk
from .retry_utils import with_retry

logger = logging.getLogger(__name__)


def _normalize_vision_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Translate vision_analyze's content-list shape into Ollama's
    native chat shape (T4-01.7).

    ``athena.vision.passthrough.passthrough_blocks(provider="ollama")``
    produces message content of the form::

        [{"type":"text","text":"What's in this image?"},
         {"type":"image","media_type":"image/png","data":"<b64>",
          "label":"tile_0_0"}]

    Ollama's ``/api/chat`` endpoint, however, expects each message
    to be ``{"role":..., "content":"<text>", "images":["<b64>",...]}``
    with a top-level ``images`` list of bare base64 strings (no
    data: prefix, no media-type wrapping). This function walks the
    message list and rewrites any list-content message into that
    shape, preserving every existing text+role property of the
    original.

    Tile labels are inlined into the text so the model can still
    refer to them in multi-turn discussion ("the magenta region in
    tile_0_1"). Non-list content (a plain string) is passed
    through untouched — chat-only turns aren't reshaped.

    Returns a fresh list; the input is never mutated.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            out.append(msg)
            continue

        text_parts: list[str] = []
        images: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                # Unknown shape — fall back to its string form so
                # at least something reaches the model.
                text_parts.append(str(block))
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append(str(block.get("text", "")))
            elif btype == "image":
                data = block.get("data")
                label = block.get("label")
                if isinstance(data, str) and data:
                    images.append(data)
                    if label:
                        # Stable handle for the model to reference
                        # this image in follow-ups.
                        text_parts.append(f"[image: {label}]")
            # Other block types (image_url Anthropic-shape, etc.)
            # don't belong in an Ollama call; we ignore them
            # rather than crash — the vision_analyze layer already
            # picks the right shape based on cfg.provider.

        new_msg = dict(msg)
        new_msg["content"] = "\n".join(p for p in text_parts if p)
        if images:
            new_msg["images"] = images
        out.append(new_msg)
    return out


# Substring patterns for known vision-capable Ollama model tags.
# Matching is case-insensitive; users typically pull the tag
# (``llava:13b`` etc.).
_VISION_MODELS = (
    "llava",
    "llama3.2-vision",
    "llama-3.2-vision",
    "bakllava",
    "moondream",
    "minicpm-v",
    "qwen2-vl",
    "qwen2.5-vl",
)


def _raise_ollama_status(response: httpx.Response) -> None:
    """Like ``response.raise_for_status()`` but reads the response body
    first so the HTTPStatusError message includes Ollama's own
    explanation. For a 404 in particular, Ollama returns
    ``{"error": "model 'foo' not found, try pulling it first"}`` —
    surfacing that beats the generic
    ``Client error '404 Not Found' for url ...`` shape that hides
    the actual reason from the user (T2-08).
    """
    if response.status_code < 400:
        return
    try:
        response.read()
        body = (response.text or "").strip()
    except Exception:
        body = ""
    # Ollama wraps the human-readable text in {"error": "..."}; strip
    # the wrapper if present so the user sees the bare message.
    try:
        parsed = json.loads(body) if body else None
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
            body = parsed["error"]
    except (json.JSONDecodeError, ValueError):
        pass
    snippet = body[:500]
    raise httpx.HTTPStatusError(
        f"{response.status_code} from {response.request.url}: {snippet}",
        request=response.request,
        response=response,
    )


@register_provider
class OllamaProvider(Provider):
    name = "ollama"
    requires_api_key = False

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        """Maximal Ollama set: SOME model has vision; the
        per-model :meth:`capabilities` narrows that. Local daemon →
        ``is_local=True`` (T5-05 broker preference) and
        ``kv_cache_reuse=True`` (T5-06 prefix-cache key). No
        server-side prompt cache."""
        return Capabilities(
            tool_calls=True,
            streaming=True,
            vision=True,
            kv_cache_reuse=True,
            structured_output=True,
            embeddings=True,
            is_local=True,
            native_format="ollama",
        )

    def capabilities(self, model: str | None = None) -> Capabilities:
        base = type(self).static_capabilities()
        if model is None:
            return base
        lower = model.lower()
        has_vision = any(v in lower for v in _VISION_MODELS)
        return dataclasses.replace(base, vision=has_vision)

    def __init__(
        self,
        host: str = "http://127.0.0.1:11434",
        *,
        timeout: float = 600.0,
        connect_timeout: float = 10.0,
        **kwargs: Any,
    ):
        super().__init__(api_key=None, **kwargs)
        self.host = host.rstrip("/")
        # Bound the CONNECT phase short so an unreachable or blackholed
        # OLLAMA_HOST fails fast instead of hanging the whole CLI launch
        # — the startup reachability probe (list_models) runs through
        # this client, and a single flat 600s timeout meant a host that
        # silently drops packets stalled launch for 10 minutes (same
        # class as the MCP startup brick). Read/write stay at the
        # generous `timeout` so long generations aren't cut off. Clamp
        # the connect bound to `timeout` so a tiny custom timeout still
        # behaves. ``_probe_timeout`` bounds the quick metadata calls
        # (list_models / show_model) end-to-end, so a host that accepts
        # the TCP connection but never answers can't hang on read either.
        self._probe_timeout = min(connect_timeout, timeout)
        self._client = httpx.Client(timeout=httpx.Timeout(timeout, connect=self._probe_timeout))
        # T2-03: retry budget. Ollama has no credential rotation
        # (single local daemon, no API key pool), but 5xx and network
        # errors against a local daemon are typically transient
        # (daemon-not-yet-ready, port still binding) and benefit
        # from the same retry policy.
        self._retry_max: int = 5
        self._retry_backoff_s: float = 30.0
        # T2-03.9: per-session retry / abort counters for /status.
        self._retry_count: int = 0
        self._abort_count: int = 0
        # Cancellation state for mid-stream interrupt. The flag is
        # checked inside _iter_stream so even buffered chunks
        # (httpx may have prefetched several before close fires) get
        # discarded immediately. Closing the Response alone wasn't
        # enough on fast local Ollama — chunks kept flowing through
        # the buffer for seconds. Belt-and-suspenders: close the
        # socket AND poll the flag.
        self._in_flight_response: httpx.Response | None = None
        self._cancelled: bool = False

    def abort_current_stream(self) -> None:
        """Cancel any in-flight stream. Sets a flag the iterator
        polls AND closes the Response so the underlying socket
        shuts down. Either path alone is racy on fast local
        servers; both together give us bounded cancellation."""
        self._cancelled = True
        r = self._in_flight_response
        if r is None:
            return
        try:
            r.close()
        except Exception:  # noqa: BLE001
            pass

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
        context-window control. The :mod:`athena.agent.param_policy`
        layer also passes ``top_p``, ``top_k``, ``repeat_penalty``,
        ``mirostat``, ``mirostat_tau``, ``mirostat_eta``, ``seed``,
        and ``stop`` through this same kwargs surface — each is
        forwarded into Ollama's ``options`` dict when present so the
        request body matches what the Ollama API documents.
        """
        # Reset cancellation state at the start of each fresh stream.
        # Without this, an aborted prior stream would leave _cancelled=True
        # and instantly abort the next request before it could yield.
        self._cancelled = False
        options: dict[str, Any] = {"temperature": temperature}
        # Each of these is opt-in via kwargs — parseltongue's policy
        # picks which ones to set per turn; other call sites can leave
        # them empty and inherit Ollama's defaults. Anything outside
        # the recognized set is dropped so a typo in a user rule
        # doesn't poison the request.
        _OLLAMA_OPTION_KEYS = (
            "top_p",
            "top_k",
            "repeat_penalty",
            "mirostat",
            "mirostat_tau",
            "mirostat_eta",
            "seed",
            "stop",
            "num_ctx",
            "presence_penalty",
            "frequency_penalty",
            "tfs_z",
            "typical_p",
        )
        for key in _OLLAMA_OPTION_KEYS:
            if key in kwargs and kwargs[key] is not None:
                options[key] = kwargs[key]
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        payload: dict[str, Any] = {
            "model": model,
            "messages": _normalize_vision_messages(messages),
            "stream": True,
            "options": options,
        }
        # keep_alive is a TOP-LEVEL field (not an options key): how long Ollama
        # keeps the model resident after the request. Used to pin the voice
        # model in VRAM between spoken turns so it doesn't pay a full reload
        # after the default 5-minute idle unload.
        keep_alive = kwargs.get("keep_alive")
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        if tools:
            payload["tools"] = tools

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
                    _raise_ollama_status(r)
                except BaseException:
                    tmp_stack.close()
                    raise
                outer_stack.push(tmp_stack.pop_all())
                return r

            r = with_retry(
                _open_response,
                max_retries=self._retry_max,
                max_backoff_s=self._retry_backoff_s,
                on_retry=lambda _c: self._inc_retry(),
                on_abort=lambda _c: self._inc_abort(),
                provider_label=self.name,
            )
            self._in_flight_response = r
            try:
                yield from self._iter_stream(r)
            finally:
                self._in_flight_response = None
            return
        finally:
            outer_stack.close()

    def _iter_stream(self, r: httpx.Response) -> Iterator[StreamChunk]:
        for line in r.iter_lines():
            # Mid-stream cancellation check. The cancel hook closes
            # the Response, but httpx may have prefetched several
            # lines into its buffer — those still flow through
            # iter_lines until the buffer empties. This flag short-
            # circuits the loop so the user's ESC has bounded effect
            # (one buffered chunk's worth, not seconds).
            if self._cancelled:
                return
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                # A malformed NDJSON line (truncated frame, a proxy
                # injecting a non-JSON keepalive, etc.) must not crash
                # the whole turn — every other SSE parser in this package
                # tolerates a bad line by skipping it.
                logger.debug("ollama: skipping unparseable stream line: %r", line[:200])
                continue
            if not isinstance(obj, dict):
                continue
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

    def _inc_retry(self) -> None:
        self._retry_count += 1

    def _inc_abort(self) -> None:
        self._abort_count += 1

    def get_retry_counts(self) -> dict[str, int]:
        """Per-session retry / abort counters (T2-03.9)."""
        return {"retries": self._retry_count, "aborts": self._abort_count}

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
        # Short per-request timeout: this is the startup reachability
        # probe; it must not inherit the 600s generation read timeout.
        r = self._client.get(f"{self.host}/api/tags", timeout=self._probe_timeout)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]

    def show_model(self, model: str) -> dict[str, Any]:
        """Fetch model metadata via ``/api/show``.

        Returns a dict with keys like ``modelfile``, ``parameters``,
        ``template``, ``system``, ``details``. The ``system`` field is
        the Modelfile SYSTEM directive — Phase 8's agent prompt builder
        prepends it to the assembled system message.
        """
        r = self._client.post(
            f"{self.host}/api/show", json={"name": model}, timeout=self._probe_timeout
        )
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        return data

    # ---- Lifecycle ----

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
