"""Factory that picks a user-model backend by config + wires it to
the agent's LLM and storage paths.

Kept in its own module (not ``__init__``) to avoid an import cycle:
``config.py`` doesn't import this, and this lazily imports each
backend so the optional Honcho deps (when added) don't load unless
the user picks that backend.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import profile_dir
from ..memory import memory_dir
from .base import BackendHealth, IngestResult, QueryResult, UserModelBackend

if TYPE_CHECKING:
    from ..config import Config


LLMCall = Callable[[str, str], Awaitable[str]]


class _DisabledBackend:
    """Sentinel backend used when ``user_model.backend = "none"``.
    Every method is a no-op so the rest of athena can call into
    the user-model surface without checking ``if backend is None``."""

    backend_name = "none"

    async def ingest_session(self, transcript, *, session_id):  # type: ignore[override]
        return IngestResult(
            facts_added=0,
            facts_updated=0,
            duration_ms=0,
            backend=self.backend_name,
        )

    async def query(self, question, *, max_tokens=800):  # type: ignore[override]
        return QueryResult(
            answer="(user model disabled — set [user_model] backend to enable)",
            sources=[],
            confidence=0.0,
        )

    def health(self) -> BackendHealth:
        return BackendHealth(
            status="ready",
            reason="user model disabled",
            backend=self.backend_name,
        )


def _resolve_storage_dir(cfg: Config) -> Path:
    return profile_dir(cfg.profile) / "user_model"


def get_user_model_backend(
    cfg: Config,
    *,
    llm_call: LLMCall | None = None,
    workspace: Path | None = None,
) -> UserModelBackend:
    """Return a backend configured per ``cfg.user_model``.

    ``llm_call`` is the async LLM-callable the backend uses for
    extraction and query. Callers pass ``None`` for the disabled
    backend (it never invokes the LLM); the markdown backend
    requires a real callable but the factory will accept ``None``
    and substitute a stub that errors at call time — that way
    misconfigured setups fail loudly at query time, not at import.

    ``workspace`` lets ``query`` mix in the user-authored memory
    files for that workspace, tagging each source ``[user]``. Pass
    ``None`` to disable the mix (auto facts only)."""
    name = (cfg.user_model.backend or "markdown").strip().lower()
    if name == "none":
        return _DisabledBackend()
    if name == "markdown":
        from .markdown import MarkdownUserModel

        return MarkdownUserModel(
            storage_dir=_resolve_storage_dir(cfg),
            llm_call=llm_call or _missing_llm_call,
            authored_memory_dir=(
                memory_dir(workspace) if workspace is not None else None
            ),
        )
    if name == "honcho":
        raise NotImplementedError(
            "Honcho backend is planned but not yet implemented. "
            "Use backend = \"markdown\" for now."
        )
    raise ValueError(
        f"unknown user_model backend {name!r}. "
        "Available: markdown, honcho, none."
    )


async def _missing_llm_call(system: str, user: str) -> str:
    """Placeholder that errors when no LLM was wired in. The
    factory accepts ``llm_call=None`` so config loading doesn't
    have to construct a provider just to validate; this stub
    surfaces the misconfiguration at first use instead."""
    raise RuntimeError(
        "user_model backend has no LLM wired. Pass llm_call when "
        "constructing the backend (see athena/agent/core.py for "
        "the wiring site)."
    )
