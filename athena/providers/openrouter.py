"""OpenRouter provider — OpenAI-compatible aggregator at openrouter.ai.

OpenRouter exposes a unified OpenAI-shaped API in front of dozens of
underlying providers (Anthropic, Google, Mistral, plus open-source
hosts). Models are addressed with a ``vendor/model`` prefix —
``anthropic/claude-3-5-sonnet``, ``openai/gpt-4o``, etc. The provider
itself doesn't care; it just forwards the model string.

The only extras beyond :class:`OpenAICompatibleProvider`:

- Custom base URL.
- ``HTTP-Referer`` / ``X-Title`` headers identify this client to
  OpenRouter's analytics — recommended by their docs even on free
  tier. Defaults point at the athena project page; callers can
  override via constructor args.
"""

from __future__ import annotations

from typing import Any

from . import register_provider
from .base import Capabilities
from .openai import OpenAICompatibleProvider

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_REFERER = "https://github.com/troofevades/athena"
_DEFAULT_TITLE = "athena"


@register_provider
class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    requires_api_key = True

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        """Broad multiplexer over many upstreams — claim the union
        of common capabilities. Vision + prompt-caching depend on
        which upstream is targeted; we declare the maximal set so
        cross-provider queries (``providers_with_capability("vision")``)
        include OpenRouter. The actual usable surface depends on the
        ``vendor/model`` the caller picks."""
        return Capabilities(
            tool_calls=True,
            streaming=True,
            vision=True,
            prompt_caching=True,  # OR passes through underlying caches
            cache_ttls_seconds=(),
            anthropic_cache_markers=True,  # passes through to Anthropic-backed models
            structured_output=True,
            max_context_tokens=200_000,
            is_local=False,
            native_format="openai",
        )

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        referer: str = _DEFAULT_REFERER,
        app_title: str = _DEFAULT_TITLE,
        timeout: float = 600.0,
        **kwargs: Any,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            extra_headers={
                "HTTP-Referer": referer,
                "X-Title": app_title,
            },
            **kwargs,
        )
