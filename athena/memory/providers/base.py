"""MemoryProvider ABC and the universal :class:`MemoryEntry` record.

A ``MemoryProvider`` is the contract for every persistent memory backend. The
built-in :class:`BuiltinFileProvider` is the default and stores memories as
Markdown files under ``<profile_dir>/memory/`` with a SQLite mirror for
ordered/queried reads. Alternate providers (Honcho, Mem0, byterover, etc.)
can be plugged in via the plugin system.

Provider methods are keyed by ``profile`` so a single provider instance can
serve every profile under ``~/.athena/profiles/<name>/``.

Provider implementations should be stateless across sessions. Per-session
state lives in :meth:`on_session_start` / :meth:`on_session_end`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class MemoryEntry:
    """One memory record. ``path`` is set by providers that back entries with
    a file on disk; non-file providers can leave it ``None``."""

    name: str
    description: str
    type: str
    body: str
    write_origin: str
    created_at: datetime
    last_activity_at: datetime
    use_count: int = 0
    path: Path | None = None


class MemoryProvider(ABC):
    """Pluggable backend for persistent memory entries.

    Concrete providers must implement every abstract method. Lifecycle hooks
    (:meth:`on_session_start`, :meth:`on_session_end`) have default no-ops so
    providers that don't need per-session bookkeeping ignore them.
    """

    name: str = ""

    @abstractmethod
    def load_index(self, profile: str, *, workspace: Path | None = None) -> str | None:
        """Return the MEMORY.md content for ``profile`` (or ``None``).

        This is the string the agent injects into the system prompt at
        session start. Truncation is the provider's responsibility — the
        agent further caps it to ``_MAX_DOCUMENT_BYTES`` defensively.

        ``workspace`` (R2 stage 1) selects a workspace-scoped sub-store
        when provided. ``None`` keeps the single-store-per-profile shape
        (what MCP server tools and the ``athena memory`` CLI use).
        """

    @abstractmethod
    def write_entry(
        self,
        profile: str,
        *,
        filename: str,
        name: str,
        description: str,
        type: str,
        body: str,
        write_origin: str,
        workspace: Path | None = None,
    ) -> Path:
        """Persist a new (or updated) memory entry. Returns the file path
        (or a synthesized path if the provider isn't file-backed).
        ``workspace`` -- see :meth:`load_index`.
        """

    @abstractmethod
    def list_entries(self, profile: str, *, workspace: Path | None = None) -> list[MemoryEntry]:
        """Return every memory under ``profile``, sorted by
        ``last_activity_at`` descending (newest first).
        ``workspace`` -- see :meth:`load_index`."""

    @abstractmethod
    def read_entry(
        self, profile: str, ident: str, *, workspace: Path | None = None
    ) -> MemoryEntry | None:
        """Return the entry matching ``ident`` (filename preferred, then
        frontmatter name), or ``None``.
        ``workspace`` -- see :meth:`load_index`."""

    @abstractmethod
    def delete_entry(self, profile: str, ident: str, *, workspace: Path | None = None) -> bool:
        """Remove an entry identified by filename (preferred) or
        frontmatter name. Returns ``True`` if the entry existed.
        ``workspace`` -- see :meth:`load_index`."""

    @abstractmethod
    def query(
        self,
        profile: str,
        *,
        query: str,
        k: int = 5,
        workspace: Path | None = None,
    ) -> list[MemoryEntry]:
        """Return the top-``k`` entries matching ``query``. Ordering and
        match semantics are provider-specific; the default
        :class:`BuiltinFileProvider` uses substring match on body and
        description, sorted by use_count then recency.
        ``workspace`` -- see :meth:`load_index`."""

    # ---- Optional lifecycle ----

    def on_session_start(self, session_id: str) -> None:
        """Called once at the start of every session."""

    def on_session_end(self, session_id: str) -> None:
        """Called once at the end of every session."""
