"""Local model-versioned vector index (T6-01.2).

At a single user's history scale, a flat JSON file plus pure-Python
cosine is plenty — no need for a server-class vector DB or a
numpy dependency. The store keeps three pieces of metadata
alongside each vector:

  ``doc_id``     callers's stable identifier (e.g. session id +
                 turn index, or memory entry name)
  ``model_id``   the embedding model the vector came from
  ``workspace``  the workspace path the doc belongs to

Search filters on ``model_id`` (always — mixing vectors from
different models is the worst-case failure for semantic recall)
and optionally on ``workspace``. Cosine similarity is computed
in pure Python; at the per-user scale this stays fast enough
without numpy.

Persistence: a single JSONL file (one entry per line). ``add``
appends one line per call — O(1) per write instead of rewriting
the whole index — and ``backfill`` rewrites once at the end.
Repeated ``add`` calls for the same ``doc_id`` accumulate on
disk; the loader dedupes by doc_id, last-wins. Atomicity isn't
critical (a crash mid-write might lose the entry being added;
the next embed-on-write recovers). Legacy pretty-printed JSON
array files are read transparently for one release.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class VectorEntry:
    """One row in the index."""

    doc_id: str
    vector: list[float]
    model_id: str
    workspace: str
    text_preview: str = ""  # short snippet; helps debugging / status

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "vector": list(self.vector),
            "model_id": self.model_id,
            "workspace": self.workspace,
            "text_preview": self.text_preview,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VectorEntry:
        return cls(
            doc_id=str(d["doc_id"]),
            vector=[float(x) for x in d.get("vector", [])],
            model_id=str(d.get("model_id", "")),
            workspace=str(d.get("workspace", "")),
            text_preview=str(d.get("text_preview", "")),
        )


class VectorStore:
    """Light JSON-backed vector index.

    ``embedder`` is the :class:`athena.recall.embeddings.Embedder`
    or any duck-compatible object with ``.embed(text)`` +
    ``.model_id``. Tests can pass a stub embedder that returns
    deterministic vectors.

    Surface:

      .add(doc_id, text, *, workspace, text_preview="")
        Embed + append. Idempotent on doc_id (a re-add overwrites
        — useful for memory entries that are rewritten).

      .search(query, *, k, workspace=None, model_id=None)
        Cosine top-k. Always filters by model_id (defaulting to
        the embedder's current model_id). Optionally filters by
        workspace. Returns doc_id list, best first.

      .backfill(items)
        Bulk add — one embedding call per item. Returns the count
        added.
    """

    def __init__(self, *, path: Path | str, embedder: Any | None = None):
        self.path = Path(path)
        self.embedder = embedder
        self._entries: list[VectorEntry] = self._load()

    # ------------------------------------------------------------------
    # Add / backfill
    # ------------------------------------------------------------------

    def add(
        self,
        doc_id: str,
        text: str,
        *,
        workspace: str,
        text_preview: str = "",
    ) -> VectorEntry | None:
        """Embed ``text`` and append (or overwrite) the entry for
        ``doc_id``. Returns the persisted entry, or None when no
        embedder is configured."""
        if self.embedder is None:
            return None
        if not text:
            return None
        vector = self.embedder.embed(text)
        if not vector:
            return None
        entry = VectorEntry(
            doc_id=doc_id,
            vector=vector,
            model_id=self.embedder.model_id,
            workspace=workspace,
            text_preview=text_preview or text[:200],
        )
        self._upsert(entry)
        self._append_one(entry)
        return entry

    def backfill(self, items: Iterable[tuple[str, str, str]]) -> int:
        """Bulk add. ``items`` yields ``(doc_id, text, workspace)``
        tuples. Returns the count of entries written. A None
        embedder yields 0 silently — callers can decide whether
        to warn."""
        if self.embedder is None:
            return 0
        count = 0
        for doc_id, text, workspace in items:
            if not text:
                continue
            try:
                vector = self.embedder.embed(text)
            except Exception as e:  # noqa: BLE001
                logger.debug("backfill: embed failed for %s: %s", doc_id, e)
                continue
            if not vector:
                continue
            self._upsert(
                VectorEntry(
                    doc_id=doc_id,
                    vector=vector,
                    model_id=self.embedder.model_id,
                    workspace=workspace,
                    text_preview=text[:200],
                )
            )
            count += 1
        if count:
            self._rewrite_all()
        return count

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        workspace: str | None = None,
        model_id: str | None = None,
    ) -> list[str]:
        """Return up to ``k`` doc_ids ranked by cosine similarity
        to ``query``. Always filters by model_id — silently
        mixing embedding spaces produces nonsense. Workspace
        filter is optional (None = no workspace filter)."""
        if self.embedder is None:
            return []
        if model_id is None:
            model_id = self.embedder.model_id
        qvec = self.embedder.embed(query)
        if not qvec:
            return []
        scored: list[tuple[float, str]] = []
        for entry in self._entries:
            if entry.model_id != model_id:
                continue
            if workspace is not None and entry.workspace != workspace:
                continue
            score = _cosine(qvec, entry.vector)
            scored.append((score, entry.doc_id))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc_id for _, doc_id in scored[: int(k)]]

    def recall(
        self,
        query: str,
        *,
        k: int = 3,
        min_score: float = 0.0,
        workspace: str | None = None,
        model_id: str | None = None,
    ) -> list[tuple[float, str]]:
        """Top-``k`` ``(score, text_preview)`` pairs at or above
        ``min_score``, ranked by cosine similarity — for auto-recall
        context injection. Like :meth:`search`, but returns the snippet
        text + score (search returns bare doc_ids) and applies a
        similarity floor so only confident matches get injected. Empty
        when there's no embedder, no query vector, or nothing clears the
        threshold."""
        if self.embedder is None:
            return []
        if model_id is None:
            model_id = self.embedder.model_id
        qvec = self.embedder.embed(query)
        if not qvec:
            return []
        scored: list[tuple[float, str]] = []
        for entry in self._entries:
            if entry.model_id != model_id:
                continue
            if workspace is not None and entry.workspace != workspace:
                continue
            if not entry.text_preview:
                continue
            score = _cosine(qvec, entry.vector)
            if score >= min_score:
                scored.append((score, entry.text_preview))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[: int(k)]

    def all(self) -> list[VectorEntry]:
        """Every entry — for admin tooling. Don't call from a
        hot path."""
        return list(self._entries)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _upsert(self, entry: VectorEntry) -> None:
        """Replace any existing entry with the same doc_id, else
        append. Keeps the index small + the latest embedding
        live for a re-written doc."""
        for i, existing in enumerate(self._entries):
            if existing.doc_id == entry.doc_id:
                self._entries[i] = entry
                return
        self._entries.append(entry)

    def _load(self) -> list[VectorEntry]:
        if not self.path.exists():
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("vector store unreadable, starting fresh: %s", e)
            return []
        if not text.strip():
            return []

        # Legacy format: a single pretty-printed JSON array. Detect by
        # checking the first non-whitespace char; one-time auto-migrate.
        stripped = text.lstrip()
        items: list[dict[str, Any]] = []
        if stripped.startswith("["):
            try:
                raw = json.loads(text)
                if isinstance(raw, list):
                    items = [r for r in raw if isinstance(r, dict)]
            except json.JSONDecodeError as e:
                logger.warning("legacy vector store unreadable, starting fresh: %s", e)
                return []
        else:
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    items.append(obj)

        # Dedupe by doc_id, last write wins. Preserves insertion order
        # for first-seen doc_ids so search ranking is stable across reloads.
        by_doc: dict[str, VectorEntry] = {}
        order: list[str] = []
        for item in items:
            try:
                entry = VectorEntry.from_dict(item)
            except (TypeError, KeyError, ValueError) as e:
                logger.warning("skipping malformed vector entry: %s", e)
                continue
            if entry.doc_id not in by_doc:
                order.append(entry.doc_id)
            by_doc[entry.doc_id] = entry
        return [by_doc[d] for d in order]

    def _append_one(self, entry: VectorEntry) -> None:
        """Append one entry's JSON to the JSONL store. O(1) per call."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), sort_keys=True))
            f.write("\n")

    def _rewrite_all(self) -> None:
        """Atomically rewrite the entire JSONL file from in-memory state.
        Used after bulk operations (backfill) and to compact away
        superseded entries that accumulated from repeated upserts."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for entry in self._entries:
                f.write(json.dumps(entry.to_dict(), sort_keys=True))
                f.write("\n")
        tmp.replace(self.path)

    def compact(self) -> None:
        """Public hook: rewrite the file from in-memory state. Removes
        accumulated superseded entries from repeated upserts. Callers
        can run this opportunistically (e.g., on session close)."""
        self._rewrite_all()


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. Returns 0.0 on zero-vector or mismatched
    dimensions — both pathological cases that shouldn't crash a
    recall call."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
