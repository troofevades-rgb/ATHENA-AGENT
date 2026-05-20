"""Out-of-band storage for large tool outputs.

When a tool produces output larger than the configured threshold,
the full output is persisted to a content-addressed blob under
``~/.athena/tool_results/`` and a short reference handle is
returned to the agent instead. The agent calls ``read_tool_result``
with the handle when it needs to read the stored content.

Public surface:

  ToolResultStorage(storage_dir, *, session_id)
  ToolResultStorage.store(content, *, tool_name) -> StoredResult
  ToolResultStorage.read(handle_or_hash, *, max_bytes, offset) -> str
  ToolResultStorage.cleanup_unreferenced(*, session_log_paths,
                                         older_than_days=30,
                                         dry_run=False) -> dict
  maybe_store_result(*, content, tool_name, threshold_bytes, storage) -> str
  HANDLE_RE
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import logging
import pathlib
import re

from ..safety.secure_files import ensure_secure_dir, secure_write_text

logger = logging.getLogger(__name__)


HANDLE_RE = re.compile(r"\[tool_result:([0-9a-f]{16})\s+—\s+([\d.]+\s*[KMG]?B)\s+output\s+stored")


@dataclasses.dataclass
class StoredResult:
    handle: str
    hash: str
    size_bytes: int
    path: pathlib.Path


class ToolResultStorage:
    """Content-addressed storage for large tool outputs."""

    def __init__(self, storage_dir: pathlib.Path, *, session_id: str) -> None:
        self.storage_dir = pathlib.Path(storage_dir).expanduser().resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.storage_dir / "index.jsonl"
        self.session_id = session_id

    # ----------------------------------------------------------------
    # Writing
    # ----------------------------------------------------------------

    def store(self, content: str, *, tool_name: str) -> StoredResult:
        """Persist ``content`` to a content-addressed blob; return the
        reference handle. Idempotent: re-storing the same content
        re-uses the existing blob (SHA-256 collision space is
        negligibly safe for this purpose)."""
        encoded = content.encode("utf-8")
        size = len(encoded)
        digest = hashlib.sha256(encoded).hexdigest()[:16]
        blob_path = self.storage_dir / f"{digest}.txt"

        if not blob_path.exists():
            secure_write_text(blob_path, content, mode=0o600)

        self._append_index(digest=digest, size=size, tool_name=tool_name)

        handle = self._build_handle(digest=digest, size_bytes=size)
        logger.info(
            "Stored tool result: tool=%s size=%d hash=%s",
            tool_name,
            size,
            digest,
        )
        return StoredResult(handle=handle, hash=digest, size_bytes=size, path=blob_path)

    def _append_index(self, *, digest: str, size: int, tool_name: str) -> None:
        entry = {
            "hash": digest,
            "size_bytes": size,
            "tool": tool_name,
            "session_id": self.session_id,
            "created_at": datetime.datetime.now(datetime.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        # O_APPEND is atomic on POSIX for short writes; one JSON object
        # per line is a single short write so cross-thread / cross-process
        # interleaving is safe.
        ensure_secure_dir(self.index_path.parent)
        with self.index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    @staticmethod
    def _build_handle(*, digest: str, size_bytes: int) -> str:
        size_str = _format_size(size_bytes)
        return f"[tool_result:{digest} — {size_str} output stored. Use read_tool_result to access.]"

    # ----------------------------------------------------------------
    # Reading
    # ----------------------------------------------------------------

    def read(self, handle_or_hash: str, *, max_bytes: int, offset: int) -> str:
        """Read up to ``max_bytes`` from the stored blob starting at
        ``offset``. Accepts either the full handle or the bare
        16-hex-char hash."""
        digest = self._extract_hash(handle_or_hash)
        if digest is None:
            raise ValueError(f"Invalid handle or hash: {handle_or_hash!r}")
        blob_path = self.storage_dir / f"{digest}.txt"
        if not blob_path.exists():
            raise FileNotFoundError(f"Blob not found: {digest}")
        with blob_path.open("rb") as f:
            f.seek(offset)
            data = f.read(max_bytes)
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _extract_hash(handle_or_hash: str) -> str | None:
        if re.fullmatch(r"[0-9a-f]{16}", handle_or_hash):
            return handle_or_hash
        m = HANDLE_RE.search(handle_or_hash)
        if m:
            return m.group(1)
        # Also accept the bare prefixed form "tool_result:<hash>" that
        # the cleanup grep scans for.
        m2 = re.search(r"tool_result:([0-9a-f]{16})", handle_or_hash)
        return m2.group(1) if m2 else None

    # ----------------------------------------------------------------
    # Cleanup
    # ----------------------------------------------------------------

    def cleanup_unreferenced(
        self,
        *,
        session_log_paths: list[pathlib.Path],
        older_than_days: int = 30,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Remove blobs not referenced by any session log AND older
        than ``older_than_days``. Recent blobs are kept regardless of
        reference state so a freshly-stored blob isn't garbage-collected
        before the session that produced it ever writes it down.

        Returns a counts dict::

            {"blobs_removed": N, "blobs_kept": M, "bytes_freed": B}

        When ``dry_run=True``, ``blobs_removed`` and ``bytes_freed``
        report what *would* be deleted; no unlinks are performed.
        """
        referenced: set[str] = set()
        for log_path in session_log_paths:
            try:
                text = log_path.read_text(errors="ignore")
            except OSError:
                continue
            for match in HANDLE_RE.finditer(text):
                referenced.add(match.group(1))
            for match in re.finditer(r"tool_result:([0-9a-f]{16})", text):
                referenced.add(match.group(1))

        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=older_than_days
        )
        removed = 0
        freed_bytes = 0
        kept = 0

        for blob_path in self.storage_dir.glob("*.txt"):
            digest = blob_path.stem
            if digest in referenced:
                kept += 1
                continue
            try:
                stat = blob_path.stat()
            except OSError:
                continue
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc)
            if mtime > cutoff:
                kept += 1
                continue
            freed_bytes += stat.st_size
            if not dry_run:
                try:
                    blob_path.unlink()
                except OSError:
                    continue
            removed += 1
            logger.info("Removed unreferenced blob: %s", digest)

        return {
            "blobs_removed": removed,
            "blobs_kept": kept,
            "bytes_freed": freed_bytes,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_size(bytes_: int) -> str:
    for unit, divisor in [("GB", 2**30), ("MB", 2**20), ("KB", 2**10)]:
        if bytes_ >= divisor:
            return f"{bytes_ / divisor:.1f}{unit}"
    return f"{bytes_}B"


def maybe_store_result(
    *,
    content: str,
    tool_name: str,
    threshold_bytes: int,
    storage: ToolResultStorage,
) -> str:
    """Store-and-return-handle if ``content`` exceeds the threshold;
    otherwise return ``content`` unchanged."""
    if len(content.encode("utf-8")) <= threshold_bytes:
        return content
    stored = storage.store(content, tool_name=tool_name)
    return stored.handle
