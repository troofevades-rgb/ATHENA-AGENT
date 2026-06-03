"""Session routing: ``(platform, chat_id, user_id) → session_id``.

Routes persist in a per-profile ``gateway.db`` so the daemon survives
restarts without losing chat continuity. The first time a chat fires,
:meth:`SessionRouter.resolve` calls ``SessionStore.open_session`` to
mint a fresh session and records the route; subsequent events for the
same (platform, chat, user) triple hit the existing row.

When :attr:`continuity` is enabled, the router consults the
``gateway_user_links`` table — humans linked via
``athena gateway link --canonical <id> --platform <p> --id <pid>``
share one session across the platforms they appear on.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .events import MessageEvent

if TYPE_CHECKING:
    from ..sessions.store import SessionStore

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS gateway_routes (
    platform        TEXT NOT NULL,
    chat_id         TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    profile         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    PRIMARY KEY (platform, chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_gateway_routes_session
    ON gateway_routes (session_id);

CREATE TABLE IF NOT EXISTS gateway_user_links (
    canonical_user_id   TEXT NOT NULL,
    platform            TEXT NOT NULL,
    platform_user_id    TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    PRIMARY KEY (platform, platform_user_id)
);

CREATE INDEX IF NOT EXISTS idx_gateway_user_links_canonical
    ON gateway_user_links (canonical_user_id);
"""


@dataclass
class Route:
    """One persisted route row — what ``athena gateway routes`` lists."""

    platform: str
    chat_id: str
    user_id: str
    session_id: str
    profile: str
    created_at: datetime
    last_seen_at: datetime


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


class SessionRouter:
    """Maps inbound platform events to a persistent session id.

    Backed by per-profile SQLite. All operations are serialized by an
    internal :class:`asyncio.Lock` so two simultaneous events on the
    same (platform, chat, user) can't both create routes — only one
    wins; the loser reads the winner's row.
    """

    def __init__(
        self,
        profile_dir: Path,
        session_store: SessionStore,
        *,
        profile: str,
        model: str,
        provider: str,
        continuity: bool = False,
    ) -> None:
        self.profile_dir = profile_dir
        self.session_store = session_store
        self.profile = profile
        self.model = model
        self.provider = provider
        self.continuity = continuity
        self._db_path = profile_dir / "gateway.db"
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._db.commit()
        self._lock = asyncio.Lock()

    # ---- resolution ----

    async def resolve(self, event: MessageEvent) -> str:
        """Return the session id for ``event``, creating one if needed.

        Resolution order:

        1. Direct match on ``(platform, chat_id, user_id)``.
        2. If continuity is enabled, look up the canonical user across
           platforms and reuse the most recent route bound to that
           canonical id.
        3. Otherwise mint a fresh session via ``SessionStore`` and
           record the new route.

        ``last_seen_at`` is bumped on every hit (cases 1 and 2) so a
        future LRU eviction can prefer the stalest routes.
        """
        async with self._lock:
            row = self._db.execute(
                "SELECT session_id FROM gateway_routes "
                "WHERE platform = ? AND chat_id = ? AND user_id = ?",
                (event.platform, event.chat_id, event.user_id),
            ).fetchone()
            if row is not None:
                self._touch_route(event)
                return row[0]

            if self.continuity:
                linked = self._lookup_via_canonical_user(event)
                if linked is not None:
                    self._record_route(event, linked)
                    return linked

            return await asyncio.to_thread(self._create_session_and_route, event)

    def _touch_route(self, event: MessageEvent) -> None:
        self._db.execute(
            "UPDATE gateway_routes SET last_seen_at = ? "
            "WHERE platform = ? AND chat_id = ? AND user_id = ?",
            (_now_iso(), event.platform, event.chat_id, event.user_id),
        )
        self._db.commit()

    def _record_route(self, event: MessageEvent, session_id: str) -> None:
        now = _now_iso()
        self._db.execute(
            "INSERT OR REPLACE INTO gateway_routes "
            "(platform, chat_id, user_id, session_id, profile, "
            " created_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event.platform,
                event.chat_id,
                event.user_id,
                session_id,
                self.profile,
                now,
                now,
            ),
        )
        self._db.commit()

    def _lookup_via_canonical_user(self, event: MessageEvent) -> str | None:
        canonical = self._canonical_user(event.platform, event.user_id)
        if canonical is None:
            return None
        # Find the most recent route for any (platform, user) pair
        # bound to this canonical user.
        rows = self._db.execute(
            "SELECT r.session_id, r.last_seen_at FROM gateway_routes r "
            "JOIN gateway_user_links l "
            "  ON r.platform = l.platform AND r.user_id = l.platform_user_id "
            "WHERE l.canonical_user_id = ? "
            "ORDER BY r.last_seen_at DESC LIMIT 1",
            (canonical,),
        ).fetchall()
        return rows[0][0] if rows else None

    def _canonical_user(self, platform: str, user_id: str) -> str | None:
        row = self._db.execute(
            "SELECT canonical_user_id FROM gateway_user_links "
            "WHERE platform = ? AND platform_user_id = ?",
            (platform, user_id),
        ).fetchone()
        return row[0] if row else None

    def _create_session_and_route(self, event: MessageEvent) -> str:
        """Mint a new session in the session store and record the route.

        Runs on a worker thread so the asyncio loop isn't blocked by
        ``SessionStore.open_session``'s synchronous SQLite writes.
        """
        from ..sessions.store import SessionMeta, new_session_id

        session_id = new_session_id()
        meta = SessionMeta(
            session_id=session_id,
            profile=self.profile,
            model=self.model,
            provider=self.provider,
            tags=[f"gateway:{event.platform}"],
        )
        try:
            self.session_store.open_session(meta)
        except Exception:
            logger.exception(
                "session_store.open_session failed for new route %s/%s",
                event.platform,
                event.chat_id,
            )
            raise
        self._record_route(event, session_id)
        return session_id

    # ---- user linking (continuity) ----

    def link_user(
        self,
        canonical_user_id: str,
        platform: str,
        platform_user_id: str,
    ) -> None:
        """Register one platform identity for a canonical user.

        Idempotent — overwriting (platform, platform_user_id) just
        re-binds it to the new canonical id.
        """
        self._db.execute(
            "INSERT OR REPLACE INTO gateway_user_links "
            "(canonical_user_id, platform, platform_user_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (canonical_user_id, platform, platform_user_id, _now_iso()),
        )
        self._db.commit()

    def unlink_user(self, platform: str, platform_user_id: str) -> bool:
        """Remove a platform identity from its canonical user. Returns
        True iff a row was actually deleted."""
        cur = self._db.execute(
            "DELETE FROM gateway_user_links WHERE platform = ? AND platform_user_id = ?",
            (platform, platform_user_id),
        )
        self._db.commit()
        return cur.rowcount > 0

    # ---- inspection ----

    def list_routes(self, *, platform: str | None = None) -> list[Route]:
        """Return every active route, optionally filtered by platform."""
        sql = (
            "SELECT platform, chat_id, user_id, session_id, profile, "
            "created_at, last_seen_at FROM gateway_routes"
        )
        params: tuple[Any, ...] = ()
        if platform is not None:
            sql += " WHERE platform = ?"
            params = (platform,)
        sql += " ORDER BY last_seen_at DESC"
        return [
            Route(
                platform=row[0],
                chat_id=row[1],
                user_id=row[2],
                session_id=row[3],
                profile=row[4],
                created_at=_parse_iso(row[5]),
                last_seen_at=_parse_iso(row[6]),
            )
            for row in self._db.execute(sql, params).fetchall()
        ]

    def remove_route(self, platform: str, chat_id: str, user_id: str) -> bool:
        cur = self._db.execute(
            "DELETE FROM gateway_routes WHERE platform = ? AND chat_id = ? AND user_id = ?",
            (platform, chat_id, user_id),
        )
        self._db.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        try:
            self._db.close()
        except sqlite3.Error:
            logger.debug("SessionRouter db close failed", exc_info=True)
