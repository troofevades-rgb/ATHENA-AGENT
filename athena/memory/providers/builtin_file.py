"""BuiltinFileProvider — the default Markdown + SQLite memory backend.

Per-profile layout::

    <profile_dir>/memory/
        MEMORY.md           # one-line index, written on every mutation
        <filename>.md       # one memory per file, YAML frontmatter
        index.db            # SQLite mirror (derived; reindexable from .md)

The Markdown files are the truth-of-record. The SQLite mirror carries
``last_activity_at``, ``use_count``, and other order-able metadata so
:meth:`list_entries` and :meth:`query` can return ordered results without
opening every file. The mirror is rebuilt from disk on every read in the
test path; production reindex is a Phase 16 concern.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ...config import profile_dir as _profile_dir
from .base import MemoryEntry, MemoryProvider

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)
_MEMORY_TYPES = {"user", "feedback", "project", "reference"}
_MEMORY_FILE_INDEX = "MEMORY.md"
_DB_FILENAME = "index.db"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str | None) -> datetime:
    if not s:
        return _now_utc()
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return _now_utc()


@dataclass
class _ParsedFile:
    fields: dict[str, str]
    body: str


def _parse_file(path: Path) -> _ParsedFile | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        fields[k.strip()] = v
    return _ParsedFile(fields=fields, body=m.group(2).strip())


class BuiltinFileProvider(MemoryProvider):
    """Markdown-on-disk memory storage with a SQLite ordering mirror.

    Constructor accepts an optional ``home`` to override ``Path.home()`` for
    tests; production callers use the default which resolves
    ``<profile_dir>(profile)`` per-call. Each ``profile`` is fully isolated.
    """

    name = "builtin_file"

    def __init__(self, home: Path | None = None):
        self._home = home

    # ---- Path helpers ---------------------------------------------------

    @staticmethod
    def workspace_slug(workspace: Path) -> str:
        """Stable, filesystem-safe slug for a workspace path.

        A short SHA-1 of the resolved path is appended so distinct
        paths that share the same letterform (e.g. ``/a/b-c`` and
        ``/a/b/c``) don't collide and share a memory directory.

        R2 stage 5 inlined this algorithm into the provider. Earlier
        stages delegated to ``athena.memory._slugify`` so the new
        ``<profile_dir>/memory/legacy/<slug>/`` layout and the legacy
        ``~/.athena/projects/<slug>/memory/`` layout produced
        byte-identical slugs (a hard requirement for the stage-4
        migrator copying between them). Algorithm preserved verbatim
        on the inline -- existing legacy data continues to map.
        """
        s = str(workspace.resolve())
        base = re.sub(r"[^a-zA-Z0-9._-]", "_", s.strip("/").replace("/", "-")) or "root"
        h = hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]
        return f"{base}_{h}"

    def _memory_dir(self, profile: str, workspace: Path | None = None) -> Path:
        """Resolve the on-disk directory for this (profile, workspace).

        ``workspace=None`` keeps the single-store-per-profile layout
        (``<profile_dir>/memory/``) used by MCP server tools and the
        ``athena memory`` CLI -- neither has a workspace concept. When
        the agent passes a workspace, entries live under
        ``<profile_dir>/memory/legacy/<workspace-slug>/`` so distinct
        workspaces under the same profile stay isolated (mirrors the
        old ``~/.athena/projects/<slug>/memory/`` shape).
        """
        base = _profile_dir(profile, home=self._home) / "memory"
        if workspace is None:
            return base
        return base / "legacy" / self.workspace_slug(workspace)

    def _ensure_dir(self, profile: str, workspace: Path | None = None) -> Path:
        d = self._memory_dir(profile, workspace=workspace)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _db_path(self, profile: str, workspace: Path | None = None) -> Path:
        return self._memory_dir(profile, workspace=workspace) / _DB_FILENAME

    # ---- SQLite mirror --------------------------------------------------

    def _connect(self, profile: str, workspace: Path | None = None) -> sqlite3.Connection:
        self._ensure_dir(profile, workspace=workspace)
        conn = sqlite3.connect(self._db_path(profile, workspace=workspace))
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_entries (
                name             TEXT PRIMARY KEY,
                filename         TEXT NOT NULL,
                description      TEXT NOT NULL DEFAULT '',
                type             TEXT NOT NULL DEFAULT 'user',
                write_origin     TEXT NOT NULL DEFAULT '',
                created_at       TEXT NOT NULL,
                last_activity_at TEXT NOT NULL,
                use_count        INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        return conn

    def _upsert_row(
        self,
        profile: str,
        *,
        name: str,
        filename: str,
        description: str,
        type: str,
        write_origin: str,
        created_at: datetime,
        last_activity_at: datetime,
        workspace: Path | None = None,
    ) -> None:
        with closing(self._connect(profile, workspace=workspace)) as conn, conn:
            conn.execute(
                """
                INSERT INTO memory_entries(name, filename, description, type,
                    write_origin, created_at, last_activity_at, use_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(name) DO UPDATE SET
                    filename = excluded.filename,
                    description = excluded.description,
                    type = excluded.type,
                    write_origin = excluded.write_origin,
                    last_activity_at = excluded.last_activity_at
                """,
                (
                    name,
                    filename,
                    description,
                    type,
                    write_origin,
                    created_at.isoformat(),
                    last_activity_at.isoformat(),
                ),
            )

    def _row_to_entry(self, row: sqlite3.Row, memory_dir: Path) -> MemoryEntry:
        path = memory_dir / row["filename"]
        body = ""
        parsed = _parse_file(path)
        if parsed is not None:
            body = parsed.body
        return MemoryEntry(
            name=row["name"],
            description=row["description"],
            type=row["type"],
            body=body,
            write_origin=row["write_origin"],
            created_at=_parse_iso(row["created_at"]),
            last_activity_at=_parse_iso(row["last_activity_at"]),
            use_count=row["use_count"],
            path=path if path.exists() else None,
        )

    # ---- MemoryProvider implementation ----------------------------------

    def load_index(self, profile: str, *, workspace: Path | None = None) -> str | None:
        index = self._memory_dir(profile, workspace=workspace) / _MEMORY_FILE_INDEX
        if not index.exists():
            return None
        try:
            text = index.read_text(encoding="utf-8")
        except OSError:
            return None
        if not text.strip():
            return None
        lines = text.splitlines()
        if len(lines) > 200:
            lines = lines[:200] + ["", "<!-- index truncated at 200 lines -->"]
        return "\n".join(lines)

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
        if type not in _MEMORY_TYPES:
            raise ValueError(
                f"invalid memory type {type!r}; must be one of {sorted(_MEMORY_TYPES)}"
            )
        if not filename.endswith(".md"):
            filename += ".md"
        if filename == _MEMORY_FILE_INDEX:
            raise ValueError(f"cannot use {_MEMORY_FILE_INDEX!r} as a memory filename")
        # Guard against prompt-injected ``filename="../../../passwd"`` —
        # the model can pass arbitrary strings here through memory_tools.
        if (
            "/" in filename
            or "\\" in filename
            or ".." in filename.split("/") + filename.split("\\")
        ):
            raise ValueError(
                f"memory filename must be a bare filename without path separators: {filename!r}"
            )
        # YAML-injection guard: ``name``, ``description``, and ``type`` are
        # interpolated raw into the frontmatter below. A value containing a
        # newline would inject arbitrary frontmatter keys (e.g.
        # ``name="foo\npinned: true"``). Reject newlines and CR explicitly
        # rather than escaping — these fields are short labels and embedded
        # control chars are never intentional.
        for field_name, value in (
            ("name", name),
            ("description", description),
            ("type", type),
            ("write_origin", write_origin),
        ):
            if "\n" in value or "\r" in value:
                raise ValueError(f"memory {field_name} must not contain newlines: {value!r}")

        d = self._ensure_dir(profile, workspace=workspace)
        target = d / filename
        if d.resolve() != target.resolve().parent:
            raise ValueError(f"resolved memory path {target} escapes memory dir {d}")
        existing_created: datetime | None = None
        if target.exists():
            parsed = _parse_file(target)
            if parsed is not None and "created_at" in parsed.fields:
                existing_created = _parse_iso(parsed.fields.get("created_at"))

        now = _now_utc()
        created_at = existing_created or now
        last_activity_at = now

        content = (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"type: {type}\n"
            f"write_origin: {write_origin}\n"
            f"created_at: {created_at.isoformat()}\n"
            f"last_activity_at: {last_activity_at.isoformat()}\n"
            "---\n\n"
            f"{body.strip()}\n"
        )
        from ...safety.mutation import snapshot_and_record

        with snapshot_and_record(
            [target] if target.exists() else [d],
            tool_name="memory_write",
        ) as ctx:
            target.write_text(content, encoding="utf-8")
            ctx.record(target)

        self._upsert_row(
            profile,
            name=name,
            filename=filename,
            description=description,
            type=type,
            write_origin=write_origin,
            created_at=created_at,
            last_activity_at=last_activity_at,
            workspace=workspace,
        )
        self._refresh_markdown_index(profile, workspace=workspace)
        return target

    def list_entries(self, profile: str, *, workspace: Path | None = None) -> list[MemoryEntry]:
        d = self._memory_dir(profile, workspace=workspace)
        if not d.exists():
            return []
        self._reconcile_from_disk(profile, workspace=workspace)
        with closing(self._connect(profile, workspace=workspace)) as conn:
            rows = conn.execute(
                "SELECT * FROM memory_entries ORDER BY last_activity_at DESC"
            ).fetchall()
        return [self._row_to_entry(r, d) for r in rows]

    def read_entry(
        self, profile: str, ident: str, *, workspace: Path | None = None
    ) -> MemoryEntry | None:
        """Read an entry by filename (preferred) or frontmatter name —
        same resolution as :meth:`delete_entry`, so ``/memory show
        <filename>`` works even when the filename differs from the
        frontmatter name."""
        d = self._memory_dir(profile, workspace=workspace)
        if not d.exists():
            return None
        self._reconcile_from_disk(profile, workspace=workspace)
        fname = ident if ident.endswith(".md") else f"{ident}.md"
        with closing(self._connect(profile, workspace=workspace)) as conn, conn:
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE filename = ? OR name = ?",
                (fname, ident),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE memory_entries SET use_count = use_count + 1 WHERE filename = ?",
                (row["filename"],),
            )
        return self._row_to_entry(row, d)

    def delete_entry(self, profile: str, ident: str, *, workspace: Path | None = None) -> bool:
        """Delete a memory entry by its FILENAME (the stable id shown by
        ``list``/``show``) or, as a fallback, its frontmatter ``name``.

        The ``delete_memory`` tool and ``/memory delete`` pass a
        filename; the entry's ``name`` is a separate frontmatter field,
        so matching on ``name`` alone silently missed the normal case
        (e.g. filename ``user_role.md`` + name ``User role``). Resolve on
        filename first (normalizing a missing ``.md``), then ``name``,
        and delete the resolved row by its filename.
        """
        d = self._memory_dir(profile, workspace=workspace)
        if not d.exists():
            return False
        self._reconcile_from_disk(profile, workspace=workspace)
        fname = ident if ident.endswith(".md") else f"{ident}.md"
        with closing(self._connect(profile, workspace=workspace)) as conn, conn:
            row = conn.execute(
                "SELECT filename FROM memory_entries WHERE filename = ? OR name = ?",
                (fname, ident),
            ).fetchone()
            if row is None:
                return False
            resolved = row["filename"]
            target = d / resolved
            if target.exists():
                from ...safety.mutation import snapshot_and_record

                with snapshot_and_record(
                    [target],
                    tool_name="memory_delete",
                ) as ctx:
                    target.unlink()
                    ctx.record(target)
            conn.execute("DELETE FROM memory_entries WHERE filename = ?", (resolved,))
        self._refresh_markdown_index(profile, workspace=workspace)
        return True

    def query(
        self,
        profile: str,
        *,
        query: str,
        k: int = 5,
        workspace: Path | None = None,
    ) -> list[MemoryEntry]:
        if k <= 0 or not query.strip():
            return []
        entries = self.list_entries(profile, workspace=workspace)
        needle = query.lower()
        matches = [
            e for e in entries if needle in e.body.lower() or needle in e.description.lower()
        ]
        matches.sort(key=lambda e: (-e.use_count, -e.last_activity_at.timestamp()))
        return matches[:k]

    # ---- Maintenance ---------------------------------------------------

    def _refresh_markdown_index(self, profile: str, workspace: Path | None = None) -> None:
        d = self._memory_dir(profile, workspace=workspace)
        if not d.exists():
            return
        lines: list[str] = ["# MEMORY index", ""]
        for p in sorted(d.iterdir()):
            if p.name in (_MEMORY_FILE_INDEX, _DB_FILENAME) or p.suffix != ".md":
                continue
            parsed = _parse_file(p)
            if parsed is None:
                continue
            fields = parsed.fields
            line = (
                f"- [{fields.get('name', p.stem)}]({p.name}) — "
                f"{fields.get('type', 'user')}: {fields.get('description', '')}"
            )
            if len(line) > 200:
                line = line[:197] + "..."
            lines.append(line)
        # Atomic write — readers (foreground + cron subprocess + background
        # review fork) always see a complete index. os.replace is atomic on
        # POSIX and Windows. Last writer wins among concurrent regenerators
        # but each individual write is durable, never torn.
        index_path = d / _MEMORY_FILE_INDEX
        tmp_path = d / (_MEMORY_FILE_INDEX + ".tmp")
        tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp_path, index_path)

    def _reconcile_from_disk(self, profile: str, workspace: Path | None = None) -> None:
        """Rebuild SQLite rows from the on-disk Markdown files.

        Cheap idempotent operation: every list/read pass through here so
        externally added / removed files don't drift from the mirror. For
        large memory stores this gets pulled into a periodic reindex
        command instead (Phase 16 territory).
        """
        d = self._memory_dir(profile, workspace=workspace)
        if not d.exists():
            return
        seen: set[str] = set()
        for p in sorted(d.iterdir()):
            if p.name in (_MEMORY_FILE_INDEX, _DB_FILENAME) or p.suffix != ".md":
                continue
            parsed = _parse_file(p)
            if parsed is None:
                continue
            fields = parsed.fields
            name = fields.get("name", p.stem)
            seen.add(name)
            created_at = _parse_iso(fields.get("created_at"))
            last_activity_at = _parse_iso(fields.get("last_activity_at"))
            self._upsert_row(
                profile,
                name=name,
                filename=p.name,
                description=fields.get("description", ""),
                type=fields.get("type", "user"),
                write_origin=fields.get("write_origin", ""),
                created_at=created_at,
                last_activity_at=last_activity_at,
                workspace=workspace,
            )
        # Drop rows for files removed externally.
        with closing(self._connect(profile, workspace=workspace)) as conn, conn:
            rows = conn.execute("SELECT name FROM memory_entries").fetchall()
            stale = [r["name"] for r in rows if r["name"] not in seen]
            for name in stale:
                conn.execute("DELETE FROM memory_entries WHERE name = ?", (name,))
