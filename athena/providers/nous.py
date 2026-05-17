"""Nous Portal provider — OpenAI-compatible API for Nous Research models.

Nous Portal (https://portal.nousresearch.com) hosts Hermes, Forge, and
the rest of the Nous family behind an OpenAI-shaped ``/v1/chat/
completions`` endpoint with a ``Bearer <key>`` authorization header.
Bog-standard subclass of :class:`OpenAICompatibleProvider` — the only
quirk is the base URL.
"""
from __future__ import annotations

from typing import Any

from . import register_provider
from .openai import OpenAICompatibleProvider


_DEFAULT_BASE_URL = "https://inference-api.nousresearch.com/v1"


@register_provider
class NousProvider(OpenAICompatibleProvider):
    name = "nous"
    requires_api_key = True

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 600.0,
        **kwargs: Any,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            **kwargs,
        )
