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

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ...config import profile_dir as _profile_dir
from .base import MemoryEntry, MemoryProvider

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S
)
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

    def _memory_dir(self, profile: str) -> Path:
        return _profile_dir(profile, home=self._home) / "memory"

    def _ensure_dir(self, profile: str) -> Path:
        d = self._memory_dir(profile)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _db_path(self, profile: str) -> Path:
        return self._memory_dir(profile) / _DB_FILENAME

    # ---- SQLite mirror --------------------------------------------------

    def _connect(self, profile: str) -> sqlite3.Connection:
        self._ensure_dir(profile)
        conn = sqlite3.connect(self._db_path(profile))
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
    ) -> None:
        with closing(self._connect(profile)) as conn, conn:
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

    def _row_to_entry(
        self, row: sqlite3.Row, memory_dir: Path
    ) -> MemoryEntry:
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

    def load_index(self, profile: str) -> str | None:
        index = self._memory_dir(profile) / _MEMORY_FILE_INDEX
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
    ) -> Path:
        if type not in _MEMORY_TYPES:
            raise ValueError(
                f"invalid memory type {type!r}; must be one of "
                f"{sorted(_MEMORY_TYPES)}"
            )
        if not filename.endswith(".md"):
            filename += ".md"
        if filename == _MEMORY_FILE_INDEX:
            raise ValueError(
                f"cannot use {_MEMORY_FILE_INDEX!r} as a memory filename"
            )

        d = self._ensure_dir(profile)
        target = d / filename
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
        )
        self._refresh_markdown_index(profile)
        return target

    def list_entries(self, profile: str) -> list[MemoryEntry]:
        d = self._memory_dir(profile)
        if not d.exists():
            return []
        self._reconcile_from_disk(profile)
        with closing(self._connect(profile)) as conn:
            rows = conn.execute(
                "SELECT * FROM memory_entries ORDER BY last_activity_at DESC"
            ).fetchall()
        return [self._row_to_entry(r, d) for r in rows]

    def read_entry(self, profile: str, name: str) -> MemoryEntry | None:
        d = self._memory_dir(profile)
        if not d.exists():
            return None
        self._reconcile_from_disk(profile)
        with closing(self._connect(profile)) as conn, conn:
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE memory_entries SET use_count = use_count + 1 WHERE name = ?",
                (name,),
            )
        return self._row_to_entry(row, d)

    def delete_entry(self, profile: str, name: str) -> bool:
        d = self._memory_dir(profile)
        if not d.exists():
            return False
        self._reconcile_from_disk(profile)
        with closing(self._connect(profile)) as conn, conn:
            row = conn.execute(
                "SELECT filename FROM memory_entries WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                return False
            target = d / row["filename"]
            if target.exists():
                from ...safety.mutation import snapshot_and_record
                with snapshot_and_record(
                    [target], tool_name="memory_delete",
                ) as ctx:
                    target.unlink()
                    ctx.record(target)
            conn.execute("DELETE FROM memory_entries WHERE name = ?", (name,))
        self._refresh_markdown_index(profile)
        return True

    def query(
        self, profile: str, *, query: str, k: int = 5
    ) -> list[MemoryEntry]:
        if k <= 0 or not query.strip():
            return []
        entries = self.list_entries(profile)
        needle = query.lower()
        matches = [
            e for e in entries
            if needle in e.body.lower() or needle in e.description.lower()
        ]
        matches.sort(
            key=lambda e: (-e.use_count, -e.last_activity_at.timestamp())
        )
        return matches[:k]

    # ---- Maintenance ---------------------------------------------------

    def _refresh_markdown_index(self, profile: str) -> None:
        d = self._memory_dir(profile)
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
        (d / _MEMORY_FILE_INDEX).write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    def _reconcile_from_disk(self, profile: str) -> None:
        """Rebuild SQLite rows from the on-disk Markdown files.

        Cheap idempotent operation: every list/read pass through here so
        externally added / removed files don't drift from the mirror. For
        large memory stores this gets pulled into a periodic reindex
        command instead (Phase 16 territory).
        """
        d = self._memory_dir(profile)
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
            )
        # Drop rows for files removed externally.
        with closing(self._connect(profile)) as conn, conn:
            rows = conn.execute(
                "SELECT name FROM memory_entries"
            ).fetchall()
            stale = [r["name"] for r in rows if r["name"] not in seen]
            for name in stale:
                conn.execute(
                    "DELETE FROM memory_entries WHERE name = ?", (name,)
                )
