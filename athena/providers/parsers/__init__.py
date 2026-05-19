"""Tool-call parser registry.

Every provider emits tool calls differently, and models within a
provider differ too: Qwen leaks XML into content, GPT-OSS uses the
harmony channel format, Anthropic returns content blocks with
``type: "tool_use"``, older OpenAI models use ``function_call`` while
newer ones use ``tool_calls``. Ollama's native format works for some
models and is bypassed by others.

A parser is a pure function::

    Parser = Callable[[str, dict], tuple[str, list[dict]]]
             (content, raw_response) -> (cleaned_content, tool_calls)

Where each ``tool_call`` is ``{"name": str, "arguments": dict, "id": str}``.

The registry is keyed by ``(provider_name, model_glob)`` and walked in
registration order — **first match wins** — then falls back to a
provider-default parser, then to the global last-resort :func:`fallback
.fallback_parser`.

Parsers self-register at import time. ``athena/providers/parsers/`` is
imported by every concrete provider's ``parse_tool_calls`` method, so
the registry is fully populated by the time anyone resolves.

Parsers MUST NOT raise. Pure logic, conservative recovery, return
``(content, [])`` on anything they can't make sense of.
"""

from __future__ import annotations

import fnmatch
import logging
from collections.abc import Callable
from typing import Any

Parser = Callable[[str, dict[str, Any]], tuple[str, list[dict[str, Any]]]]


logger = logging.getLogger(__name__)


_REGISTRY: list[tuple[str, str, Parser]] = []  # ordered: (provider, model_glob, parser)
_DEFAULTS: dict[str, Parser] = {}  # provider -> default parser


def register(provider: str, model_glob: str, parser: Parser) -> None:
    """Register ``parser`` for a (provider, model_glob) pair.

    Registration order matters: ``resolve_parser`` walks the list and
    returns the first match. Register narrow globs (``"gpt-4-0613"``)
    before wide ones (``"gpt-4*"``).
    """
    _REGISTRY.append((provider, model_glob, parser))


def register_default(provider: str, parser: Parser) -> None:
    """Register a provider-wide default parser. Used when no (provider,
    model_glob) entry matched."""
    _DEFAULTS[provider] = parser


def resolve_parser(provider: str, model: str) -> Parser:
    """Return the best-matching parser for ``(provider, model)``.

    Lookup order:
      1. (provider, model_glob) entries, first-match-wins.
      2. provider-wide default registered via :func:`register_default`.
      3. global :func:`fallback.fallback_parser`.
    """
    lower_model = (model or "").lower()
    for p, glob, parser in _REGISTRY:
        if p == provider and fnmatch.fnmatch(lower_model, glob.lower()):
            return parser
    if provider in _DEFAULTS:
        return _DEFAULTS[provider]
    # Lazy import: fallback module imports the registry too; defer to
    # avoid a circular dependency on first import.
    from .fallback import fallback_parser

    return fallback_parser


def clear_registry() -> None:
    """Drop every registered parser. Test affordance — call this in a
    fixture and re-import the parser package to start fresh."""
    _REGISTRY.clear()
    _DEFAULTS.clear()


# Side-effect imports so each parser's ``register()`` call fires at
# package load. Each is wrapped in try/except so a partial parser set
# during development doesn't take down the whole registry.
for _module in (
    "anthropic_xml",
    "openai_function",
    "openai_tools",
    "ollama_native",
    "qwen_xml_leakage",
    "harmony",
    "code_fenced_json",
    "json_block",
    "fallback",
):
    try:
        __import__(f"{__name__}.{_module}", fromlist=["*"])
    except ImportError as e:  # pragma: no cover — only fires during partial dev
        logger.info("parser module %s not yet present: %s", _module, e)


__all__ = [
    "Parser",
    "register",
    "register_default",
    "resolve_parser",
    "clear_registry",
]
