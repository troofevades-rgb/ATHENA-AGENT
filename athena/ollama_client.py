"""Back-compat shim — the real implementation moved to
``athena.providers.ollama`` in Phase 8.

This module re-exports :class:`OllamaProvider` under its v1 name
``OllamaClient`` and keeps the :class:`ChatChunk` dataclass alive for
any out-of-tree code that imported it. Scheduled for removal one
release after Phase 8.

Note that ``ChatChunk`` no longer corresponds to anything the Phase 8
provider yields — providers now yield :class:`athena.providers.StreamChunk`.
``ChatChunk`` here is purely for import compatibility; constructing one
won't get you a usable response.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .providers.ollama import OllamaProvider as OllamaClient  # noqa: F401


@dataclass
class ChatChunk:
    """Deprecated v1 chunk shape — present only so legacy imports don't
    break. Phase 8 providers yield :class:`athena.providers.StreamChunk`."""

    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    done: bool = False
    raw: dict[str, Any] | None = None


__all__ = ["ChatChunk", "OllamaClient"]
