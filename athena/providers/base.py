"""Provider ABC and the universal :class:`StreamChunk` shape.

Every backend (Ollama, Anthropic, OpenAI, Google, ...) implements this
contract. The downstream agent loop is provider-agnostic — provider
differences are absorbed at the boundary.

``StreamChunk`` is a discriminated record:

- ``content`` — payload is a ``str`` of generated text.
- ``tool_call`` — payload is ``{"name": str, "arguments": dict|str, "id": str}``.
- ``usage`` — payload is ``{"prompt_tokens": int, "completion_tokens": int}``.
- ``end`` — payload is ``{"reason": "stop" | "length" | "tool_calls" | ...}``.

Providers that speak something other than the agent's native format are
responsible for translating their native stream into these chunks
before yielding.
"""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

ChunkKind = Literal["content", "tool_call", "usage", "end"]


@dataclass
class StreamChunk:
    """One streamed chunk from a provider. ``kind`` discriminates the
    ``payload`` shape; consumers branch on it."""

    kind: ChunkKind
    payload: Any

    @property
    def content(self) -> str:
        """Convenience accessor: empty string for non-content chunks."""
        return self.payload if self.kind == "content" and isinstance(self.payload, str) else ""


@dataclasses.dataclass(frozen=True)
class Capabilities:
    """Declarative provider manifest (T5-01R).

    Data, never behavior. New capabilities default OFF (opt-in);
    ``tool_calls`` and ``streaming`` default ON so folding the
    existing ``supports_tools`` / ``supports_streaming`` methods
    into delegators reading this manifest is byte-identical with
    today's behaviour.

    The fields cover the capability axes downstream phases key off:

    - ``tool_calls`` / ``streaming`` — the existing two-field surface
    - ``vision`` + ``max_image_edge_px`` — multimodal input
    - ``prompt_caching`` + ``cache_ttls_seconds`` — server-side
      prefix caches (Anthropic, OpenAI, OpenRouter, Nous)
    - ``kv_cache_reuse`` — local-machine prefix cache (Ollama)
    - ``structured_output`` — JSON / strict-schema responses
    - ``embeddings`` — separate embedding endpoint
    - ``max_context_tokens`` — hard context limit
    - ``is_local`` — broker preference signal
    - ``native_format`` — the request/response shape on the wire
      (``"openai"``, ``"anthropic"``, ``"ollama"``, ``"google"``)
    - ``social_search`` — provider can search a social network
      (X / similar) for real-time public posts (T6-02). The
      broker routes a ``search_x`` sub-task to a provider
      declaring this capability even when a different model is
      primary. Defaults False so nothing routes by accident.
    """

    tool_calls: bool = True
    streaming: bool = True
    vision: bool = False
    max_image_edge_px: int | None = None
    prompt_caching: bool = False
    cache_ttls_seconds: tuple[int, ...] = ()
    kv_cache_reuse: bool = False
    structured_output: bool = False
    embeddings: bool = False
    max_context_tokens: int | None = None
    is_local: bool = False
    native_format: str = "openai"
    social_search: bool = False
    # T6-05: native video generation (text→video, image→video).
    # The broker routes ``video_generate`` / ``animate_image``
    # sub-tasks to providers declaring this capability. Defaults
    # False; the in-tree video providers declare it explicitly
    # in their static_capabilities().
    video_generation: bool = False

    def supports(self, capability: str) -> bool:
        """``True`` when the named field is truthy. Lets callers
        check capabilities by name without reflecting on the dataclass
        fields directly."""
        return bool(getattr(self, capability, False))


class Provider(ABC):
    """Minimum surface every provider must expose.

    Subclasses register themselves via the :func:`register_provider`
    decorator on import. Construction arguments differ per provider —
    Ollama takes a ``host``, Anthropic takes an ``api_key``, etc. The
    :func:`runtime_resolver.resolve_provider` machinery (Prompt 8.6)
    bridges from config to constructor.
    """

    # Stable identifier used by the registry and routing. Subclasses must
    # set this; instances don't override it on a per-call basis.
    name: str = ""

    # Whether the provider needs an API key. False for local Ollama and
    # for openai_compat (host-only). True for hosted providers.
    requires_api_key: bool = True

    def __init__(self, api_key: str | None = None, **kwargs: Any):
        self.api_key = api_key
        self.kwargs = kwargs

    # ---- Core stream API ----

    @abstractmethod
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
        """Stream a chat completion. Yield :class:`StreamChunk` objects in
        the canonical four kinds (content, tool_call, usage, end)."""

    @abstractmethod
    def parse_tool_calls(
        self, content: str, raw_response: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Extract tool calls from a finished assistant message.

        Returns ``(cleaned_content, [{name, arguments, id}, ...])``.
        ``cleaned_content`` is the assistant content with any tool-call
        markup removed (Qwen XML, OpenAI function-call text leak, etc.).

        Phase 9's per-provider parser registry will plug in here. For now
        most providers can delegate to a thin shared parser.
        """

    # ---- Optional capabilities ----

    def count_tokens(self, text: str) -> int:
        """Rough estimate: ~1 token per 0.75 words. Providers with their
        own tokenizers should override."""
        if not text:
            return 0
        return int(len(text.split()) / 0.75) or 1

    # ---- Capability manifest (T5-01R) --------------------------------

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        """Class-level maximal capability set, suitable for cross-
        provider registry queries (``providers_with_capability`` etc.)
        without instantiation. Override per provider to declare
        honest capabilities.

        The base default mirrors the historical behaviour of
        ``supports_tools`` / ``supports_streaming``: both True; every
        other capability conservatively False."""
        return Capabilities()

    def capabilities(self, model: str | None = None) -> Capabilities:
        """This instance's capabilities, optionally refined for a
        specific ``model``. Defaults to the class baseline; override
        to refine per-model (e.g. Ollama: vision only for vision
        models, mirroring how the original ``supports_tools(model)``
        was already model-aware)."""
        return type(self).static_capabilities()

    def supports_tools(self, model: str) -> bool:
        """Fold into the manifest as a delegator. Signature
        unchanged; behaviour preserved by the True default on
        ``Capabilities.tool_calls``."""
        return self.capabilities(model).tool_calls

    def supports_streaming(self, model: str) -> bool:
        """Same fold as ``supports_tools``."""
        return self.capabilities(model).streaming

    # ---- Discovery (Ollama-flavored; safe defaults for hosted providers) ----

    def list_models(self) -> list[str]:
        """Return locally / remotely available model names. Hosted providers
        may not implement this; default is empty."""
        return []

    def show_model(self, model: str) -> dict[str, Any]:
        """Return model metadata. The ``system`` key, if present, is the
        baked-in Modelfile SYSTEM directive (Ollama-only concept). Default
        is empty for providers without an equivalent — the agent already
        handles a missing key gracefully.
        """
        return {}

    # ---- Lifecycle ----

    def close(self) -> None:
        """Release any held resources (httpx clients, etc.). Default no-op
        so providers that don't open connections eagerly don't need to
        override."""
