"""Generic OpenAI-compatible provider.

Many local and hosted inference servers expose an OpenAI-shaped
``/chat/completions`` endpoint: vLLM, llama.cpp's server, TabbyAPI, LM
Studio, Ollama's own ``/v1`` shim, and the long tail of self-hosted
gateways. The only thing that varies is the base URL and whether an
API key is required.

This provider takes both as constructor arguments and otherwise
inherits all behavior from :class:`OpenAICompatibleProvider` (the
SSE-parsing base in :mod:`athena.providers.openai`).
"""

from __future__ import annotations

from typing import Any

from . import register_provider
from .base import Capabilities
from .openai import OpenAICompatibleProvider


@register_provider
class OpenAICompatProvider(OpenAICompatibleProvider):
    name = "openai_compat"
    requires_api_key = False  # local servers often don't require one

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        """Conservative — the backend is host-defined (vLLM,
        llama.cpp, etc.). Claim only what's universally true for
        the OpenAI-compatible /v1/chat/completions surface: tool
        calls + streaming. Vision, embeddings, caching are
        host-specific; leave them off so the broker / queries
        don't over-promise."""
        return Capabilities(
            tool_calls=True,
            streaming=True,
            is_local=False,  # host-configured; could be local or remote
            native_format="openai",
        )

    def __init__(
        self,
        api_key: str | None = None,
        *,
        host: str,
        timeout: float = 600.0,
        extra_headers: dict[str, str] | None = None,
        **kwargs: Any,
    ):
        """``host`` is required — there's no sensible default for a
        generic compat endpoint (it could be anywhere on localhost or
        a private VPC).
        """
        # Normalize host: accept either "http://host:8000" or
        # "http://host:8000/v1" — append /v1 if it's not already there.
        cleaned = host.rstrip("/")
        if not cleaned.endswith("/v1"):
            cleaned = cleaned + "/v1"
        super().__init__(
            api_key=api_key,
            base_url=cleaned,
            timeout=timeout,
            extra_headers=extra_headers,
            **kwargs,
        )
