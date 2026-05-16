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

    def supports_tools(self, model: str) -> bool:
        return True

    def supports_streaming(self, model: str) -> bool:
        return True

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
