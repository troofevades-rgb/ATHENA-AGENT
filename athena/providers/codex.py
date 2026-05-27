"""OpenAI Codex provider — codex-mini and related models via OpenRouter.

Routes ``codex/<model>`` and bare ``codex-*`` model names through
OpenRouter's OpenAI-compatible endpoint. Registers separately from the
``openrouter`` provider so the credential pool, routing, and capability
manifest are independent.

Default model: ``codex-mini-latest``.
"""

from __future__ import annotations

from . import register_provider
from .base import Capabilities
from .openai import OpenAICompatibleProvider

_DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1"


@register_provider
class CodexProvider(OpenAICompatibleProvider):
    name = "codex"

    def _default_base_url(self) -> str:
        return _DEFAULT_OPENROUTER_URL

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        return Capabilities(
            tool_calls=True,
            streaming=True,
            vision=False,
            prompt_caching=True,
            structured_output=True,
            max_context_tokens=192_000,
            is_local=False,
            native_format="openai",
        )
