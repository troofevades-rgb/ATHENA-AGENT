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
from .openai import OpenAICompatibleProvider

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_REFERER = "https://github.com/troofevades/athena"
_DEFAULT_TITLE = "athena"


@register_provider
class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    requires_api_key = True

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
