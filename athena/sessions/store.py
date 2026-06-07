"""SessionStore: per-profile JSONL append store with SQLite FTS5 mirror.

Workflow per session:

  1. ``open_session(meta)`` creates ``<id>.jsonl``, writes ``<id>.meta.json``,
     and inserts a sessions row.
  2. ``append_turn(id, msg)`` appends to the JSONL (truth) and mirrors to
     SQLite (cache). On SQLite failure the JSONL write still succeeds and
     ``athena reindex`` will catch up.
  3. ``close_session(id)`` stamps ``ended_at`` on both the meta file and the
     sessions row.

``search`` returns :class:`SearchHit` objects with surrounding turns
included so the model has enough context to act on the match.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import threading
import weakref
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from . import jsonl, sqlite_index

logger = logging.getLogger(__name__)


# -- UUIDv7 (timestamp + random) ------------------------------------------


def new_session_id() -> str:
    """Generate a UUIDv7 string. 48-bit unix-ms timestamp followed by version,
    variant, and random bits — time-ordered for natural sort and uniqueness
    safe against concurrent generation in the same millisecond."""
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    ts_hex = f"{ts_ms:012x}"
    rand_a = secrets.randbits(12)  # 12 bits after version nibble
    rand_b = secrets.randbits(62)  # 62 bits after variant prefix
    # version 7 nibble + 12-bit rand_a
    ver_and_a = (0x7 << 12) | rand_a
    # variant '10' in top two bits of the next 64
    var_and_b = (0b10 << 62) | rand_b
    return (
        f"{ts_hex[0:8]}-"
        f"{ts_hex[8:12]}-"
        f"{ver_and_a:04x}-"
        f"{(var_and_b >> 48) & 0xFFFF:04x}-"
        f"{var_and_b & 0xFFFFFFFFFFFF:012x}"
    )


# -- Data classes --------------------------------------------------------


@dataclass
class SessionMeta:
    session_id: str
    profile: str
    model: str
    provider: str = "ollama"
    workspace: str | None = None
    parent_session_id: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class SearchHit:
    session_id: str
    turn_index: int
    role: str
    snippet: str
    surrounding: list[dict[str, Any]]
    score: float
    started_at: datetime
    workspace: str | None = None


@dataclass
class SessionVerifyRow:
    """One session's JSONL-vs-SQLite consistency result (see
    :meth:`SessionStore.verify`)."""

    session_id: str
    jsonl_turns: int  # -1 when the .jsonl file is missing
    db_turns: int
    indexed: bool  # has a row in the sessions table
    ok: bool


# -- The store -----------------------------------------------------------


class SessionStore:
    """Per-profile session index + JSONL transcripts.

    SQLite connection strategy (Phase 17 stress fix): one connection
    per thread, opened lazily on first access. Sharing a single
    connection across many writer threads with
    ``check_same_thread=False`` produced races under stress
    (concurrent INSERT bursts surfaced as ``SystemError: error
    return without exception set`` and ``Cannot operate on a closed
    database``). SQLite's file lock serialises writes between
    separate connections cleanly, so per-thread connections are the
    correct shape for concurrent gateway dispatch.
    """

    def __init__(self, profile_dir: Path) -> None:
        self.profile_dir = profile_dir
        self.sessions_dir = profile_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = profile_dir / "sessions.db"
        self._closed = False
        # Thread-local connections. Each thread that touches the
        # store gets its own sqlite3.Connection (lazy first-use).
        # We track them all on _connections so close() can shut every
        # one down on daemon teardown.
        self._tls = threading.local()
        # Each entry is (weakref-to-owning-thread, connection). The
        # weakref lets _conn() detect threads that have exited and
        # close their connections, instead of leaking the sqlite
        # handle (+ WAL shm/wal files) for the life of the process.
        # Long-lived daemons that spawn many short threads (cron jobs,
        # review forks) used to accumulate one connection per thread
        # until close(). Now they get reaped opportunistically.
        self._connections: list[tuple[weakref.ref[threading.Thread], sqlite3.Connection]] = []
        self._connections_lock = threading.Lock()
        # Initialise schema once on the constructing thread; this also
        # opens the first per-thread connection.
        sqlite_index.init_schema(self._conn())

    def _conn(self) -> sqlite3.Connection:
        """Return this thread's sqlite3 connection, opening one on
        first call. Raises ``RuntimeError`` after ``close()``.

        Opportunistically closes connections whose owning thread has
        died so they don't pile up across the process lifetime."""
        if self._closed:
            raise RuntimeError("SessionStore is closed")
        conn = getattr(self._tls, "conn", None)
        if conn is not None:
            return cast(sqlite3.Connection, conn)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error:
            logger.debug("WAL pragma not available", exc_info=True)
        self._tls.conn = conn
        thread_ref = weakref.ref(threading.current_thread())
        with self._connections_lock:
            # Reap dead-thread entries while we hold the lock anyway.
            survivors: list[tuple[weakref.ref[threading.Thread], sqlite3.Connection]] = []
            for ref, c in self._connections:
                if ref() is None:
                    try:
                        c.close()
                    except sqlite3.Error:
                        pass
                else:
                    survivors.append((ref, c))
            survivors.append((thread_ref, conn))
            self._connections = survivors
        return conn

    # -- session lifecycle -------------------------------------------

    def open_session(self, meta: SessionMeta) -> None:
        jsonl_path = self.sessions_dir / f"{meta.session_id}.jsonl"
        meta_path = self.sessions_dir / f"{meta.session_id}.meta.json"
        # Touch the JSONL file so count_lines and downstream consumers can
        # rely on its existence even before the first turn.
        jsonl_path.touch(exist_ok=True)
        meta_path.write_text(_meta_to_json(meta), encoding="utf-8")
        try:
            sqlite_index.insert_session(self._conn(), _meta_to_dict(meta))
        except sqlite3.Error as e:
            logger.warning("sqlite open_session failed for %s: %s", meta.session_id, e)

    def append_turn(self, session_id: str, message: dict[str, Any]) -> int:
        jsonl_path = self.sessions_dir / f"{session_id}.jsonl"
        turn_index = jsonl.count_lines(jsonl_path)
        jsonl.append_jsonl(jsonl_path, message)

        role = str(message.get("role") or "user")
        content = _flatten_content(message)
        tool_name = message.get("name") if role == "tool" else None
        timestamp = message.get("timestamp") or _now_iso()

        try:
            sqlite_index.insert_turn(
                self._conn(),
                session_id,
                turn_index,
                role,
                content,
                tool_name,
                timestamp,
            )
        except sqlite3.Error as e:
            logger.warning(
                "sqlite append_turn failed for %s[%d]: %s — JSONL is intact, "
                "run `athena reindex` to rebuild",
                session_id,
                turn_index,
                e,
            )
        return turn_index

    def close_session(self, session_id: str, ended_at: datetime | None = None) -> None:
        ended = ended_at or datetime.now(timezone.utc)
        meta_path = self.sessions_dir / f"{session_id}.meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
            meta["ended_at"] = ended.isoformat()
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        try:
            sqlite_index.update_session_ended(self._conn(), session_id, ended)
        except sqlite3.Error as e:
            logger.warning("sqlite close_session failed for %s: %s", session_id, e)

    # -- read paths --------------------------------------------------

    def list_sessions(
        self,
        *,
        limit: int = 50,
        before: datetime | None = None,
    ) -> list[SessionMeta]:
        where = ""
        params: list[Any] = []
        if before is not None:
            where = "WHERE started_at < ?"
            params.append(before.isoformat())
        sql = (
            "SELECT session_id, profile, model, provider, workspace, "
            "parent_session_id, started_at, ended_at, tags FROM sessions "
            f"{where} ORDER BY started_at DESC LIMIT ?"
        )
        params.append(limit)
        rows = self._conn().execute(sql, params).fetchall()
        out: list[SessionMeta] = []
        for r in rows:
            out.append(
                SessionMeta(
                    session_id=r[0],
                    profile=r[1],
                    model=r[2],
                    provider=r[3],
                    workspace=r[4],
                    parent_session_id=r[5],
                    started_at=_parse_iso(r[6]),
                    ended_at=_parse_iso(r[7]) if r[7] else None,
                    tags=json.loads(r[8] or "[]"),
                )
            )
        return out

    def get_session(self, session_id: str) -> SessionMeta | None:
        """Fetch one session's metadata by id, or ``None`` if unknown."""
        row = (
            self._conn()
            .execute(
                "SELECT session_id, profile, model, provider, workspace, "
                "parent_session_id, started_at, ended_at, tags FROM sessions "
                "WHERE session_id = ?",
                (session_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return SessionMeta(
            session_id=row[0],
            profile=row[1],
            model=row[2],
            provider=row[3],
            workspace=row[4],
            parent_session_id=row[5],
            started_at=_parse_iso(row[6]),
            ended_at=_parse_iso(row[7]) if row[7] else None,
            tags=json.loads(row[8] or "[]"),
        )

    def load(self, session_id: str) -> Iterator[dict[str, Any]]:
        yield from jsonl.read_jsonl(self.sessions_dir / f"{session_id}.jsonl")

    def verify(self) -> list[SessionVerifyRow]:
        """Compare each session's JSONL truth against the SQLite mirror.

        ``append_turn`` writes one ``turns`` row per JSONL line, so a
        healthy session has a ``.jsonl`` file, a ``sessions``-table row,
        and an equal count of JSONL lines and ``turns`` rows. A mismatch
        means the mirror drifted behind a crashed write (FTS search then
        silently degrades) — ``athena reindex`` rebuilds it from the
        JSONL. Returns one row per known session id (the union of on-disk
        ``.jsonl`` files and indexed sessions) so orphans in either
        direction surface too.
        """
        conn = self._conn()
        jsonl_ids = {p.stem for p in self.sessions_dir.glob("*.jsonl")}
        table_ids = {r[0] for r in conn.execute("SELECT session_id FROM sessions").fetchall()}
        turn_counts: dict[str, int] = {
            r[0]: int(r[1])
            for r in conn.execute(
                "SELECT session_id, COUNT(*) FROM turns GROUP BY session_id"
            ).fetchall()
        }
        out: list[SessionVerifyRow] = []
        for sid in sorted(jsonl_ids | table_ids | turn_counts.keys()):
            jpath = self.sessions_dir / f"{sid}.jsonl"
            jturns = jsonl.count_lines(jpath) if jpath.exists() else -1
            dturns = turn_counts.get(sid, 0)
            indexed = sid in table_ids
            ok = jturns >= 0 and indexed and jturns == dturns
            out.append(SessionVerifyRow(sid, jturns, dturns, indexed, ok))
        return out

    def most_recent_other_session(self, *, exclude: str | None) -> SessionMeta | None:
        """Return the most recently *ended* session other than ``exclude``.

        Used by the curator's idle gate: if the user closed another session
        in the last N hours, skip this run. Open sessions (ended_at IS NULL)
        are ignored so an unclosed parent doesn't postpone the curator
        indefinitely.
        """
        sql = (
            "SELECT session_id, profile, model, provider, workspace, "
            "parent_session_id, started_at, ended_at, tags FROM sessions "
            "WHERE ended_at IS NOT NULL AND session_id != ? "
            "ORDER BY ended_at DESC LIMIT 1"
        )
        row = self._conn().execute(sql, (exclude or "",)).fetchone()
        if row is None:
            return None
        return SessionMeta(
            session_id=row[0],
            profile=row[1],
            model=row[2],
            provider=row[3],
            workspace=row[4],
            parent_session_id=row[5],
            started_at=_parse_iso(row[6]),
            ended_at=_parse_iso(row[7]),
            tags=json.loads(row[8] or "[]"),
        )

    def children(self, session_id: str) -> list[SessionMeta]:
        """Return every session whose ``parent_session_id`` is ``session_id``,
        ordered by ``started_at`` ascending so the tree displays chronologically."""
        rows = (
            self._conn()
            .execute(
                "SELECT session_id, profile, model, provider, workspace, "
                "parent_session_id, started_at, ended_at, tags FROM sessions "
                "WHERE parent_session_id = ? ORDER BY started_at ASC",
                (session_id,),
            )
            .fetchall()
        )
        return [
            SessionMeta(
                session_id=r[0],
                profile=r[1],
                model=r[2],
                provider=r[3],
                workspace=r[4],
                parent_session_id=r[5],
                started_at=_parse_iso(r[6]),
                ended_at=_parse_iso(r[7]) if r[7] else None,
                tags=json.loads(r[8] or "[]"),
            )
            for r in rows
        ]

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        workspace: str | None = None,
        since: datetime | None = None,
    ) -> list[SearchHit]:
        rows = sqlite_index.fts5_search(self._conn(), query, k=k, workspace=workspace, since=since)
        hits: list[SearchHit] = []
        for (
            session_id,
            turn_index,
            role,
            content,
            tool_name,
            _timestamp,
            started_at_str,
            ws,
            score,
        ) in rows:
            surrounding = self._surrounding(session_id, turn_index)
            hits.append(
                SearchHit(
                    session_id=session_id,
                    turn_index=turn_index,
                    role=role,
                    snippet=_snippet(content),
                    surrounding=surrounding,
                    score=float(score) if score is not None else 0.0,
                    started_at=_parse_iso(started_at_str),
                    workspace=ws,
                )
            )
        return hits

    # -- internals ---------------------------------------------------

    def _surrounding(self, session_id: str, turn_index: int) -> list[dict[str, Any]]:
        """Return [prev, hit, next] turns (skips missing ends)."""
        wanted = {turn_index - 1, turn_index, turn_index + 1}
        out: list[dict[str, Any]] = []
        for i, msg in enumerate(self.load(session_id)):
            if i in wanted:
                out.append({"turn_index": i, **msg})
            if i > turn_index + 1:
                break
        return out

    def close(self) -> None:
        """Close every thread-local connection. Safe to call from
        any thread; idempotent so daemon shutdown can fire it even
        if a SessionStore was never actually used."""
        self._closed = True
        with self._connections_lock:
            connections = [c for _ref, c in self._connections]
            self._connections.clear()
        for conn in connections:
            try:
                conn.close()
            except sqlite3.Error:
                pass


# -- module helpers ------------------------------------------------------


_SNIPPET_MAX = 300


def _snippet(content: str) -> str:
    content = content.strip().replace("\n", " ")
    if len(content) <= _SNIPPET_MAX:
        return content
    return content[: _SNIPPET_MAX - 3] + "..."


def _flatten_content(message: dict[str, Any]) -> str:
    """Turn an assistant or tool message into a flat string suitable for FTS5.
    Assistant messages may have tool_calls; we serialize the call name and
    arguments so they're searchable too."""
    parts: list[str] = []
    content = message.get("content")
    if isinstance(content, str) and content:
        parts.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        name = fn.get("name", "")
        args = fn.get("arguments", "")
        if isinstance(args, (dict, list)):
            args = json.dumps(args, ensure_ascii=False)
        parts.append(f"[tool_call:{name}] {args}")
    return "\n".join(p for p in parts if p)


def _meta_to_dict(meta: SessionMeta) -> dict[str, Any]:
    d = asdict(meta)
    d["started_at"] = (
        meta.started_at.isoformat() if isinstance(meta.started_at, datetime) else meta.started_at
    )
    d["ended_at"] = (
        meta.ended_at.isoformat()
        if isinstance(meta.ended_at, datetime) and meta.ended_at
        else meta.ended_at
    )
    return d


def _meta_to_json(meta: SessionMeta) -> str:
    return json.dumps(_meta_to_dict(meta), indent=2, default=str)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
