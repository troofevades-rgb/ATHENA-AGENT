"""xAI provider -- Grok chat models at api.x.ai.

xAI exposes an OpenAI-compatible ``/v1/chat/completions`` endpoint
with a ``Bearer <key>`` authorization header. Bog-standard subclass
of :class:`OpenAICompatibleProvider`; the only quirks are the base
URL and the vision capability (Grok 2 vision and later support
image input).

Route a model to this provider with the ``xai/`` prefix (e.g.
``xai/grok-2``, ``xai/grok-2-vision-1212``). The prefix is stripped
before the model name goes on the wire because xAI expects the bare
``grok-...`` form.

Authentication: an API key from https://console.x.ai/ either via the
credential pool (``athena providers add-credential xai <key>``) or
passed directly at construction in tests.

Prompt caching: xAI's caching is server-side automatic (similar to
OpenAI's), so :attr:`Capabilities.prompt_caching` is True but
:attr:`anthropic_cache_markers` stays False -- we don't send
``cache_control`` markers on the wire.
"""

from __future__ import annotations

from typing import Any

from . import register_provider
from .base import Capabilities
from .openai import OpenAICompatibleProvider

_DEFAULT_BASE_URL = "https://api.x.ai/v1"


@register_provider
class XAIProvider(OpenAICompatibleProvider):
    name = "xai"
    requires_api_key = True

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        """Grok family: tool-calls, streaming, vision on
        ``grok-2-vision`` and later, structured output, 131k context
        on the current generation. Prompt caching is automatic on
        the server side -- declare the capability so the broker
        knows the provider caches, but leave
        ``anthropic_cache_markers`` False because xAI doesn't expect
        client-side markers."""
        return Capabilities(
            tool_calls=True,
            streaming=True,
            vision=True,
            max_image_edge_px=2048,
            prompt_caching=True,
            cache_ttls_seconds=(),
            anthropic_cache_markers=False,
            structured_output=True,
            max_context_tokens=131_072,
            is_local=False,
            native_format="openai",
        )

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 600.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            **kwargs,
        )
