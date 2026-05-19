"""Cross-platform user linking.

When :attr:`GatewayConfig.continuity` is enabled, the router consults
the ``gateway_user_links`` table to decide whether two messages from
different platforms belong to the same human's conversation.

The table itself (and the per-row link primitives) live on
:class:`~athena.gateway.router.SessionRouter` because the resolve
path needs them directly. This module is a thin façade that adds:

- :meth:`link_canonical` — register one canonical user with their IDs
  on multiple platforms in one call (so the CLI's
  ``athena gateway link --canonical alice --telegram tg-1
  --slack sl-1`` is one transaction, not three).
- :meth:`unlink_canonical` — drop every binding for a canonical user
  at once.
- :meth:`platforms_for` — list every (platform, platform_user_id)
  pair bound to a canonical id; surfaces in
  ``athena gateway routes --canonical <id>``.

Keeping these façades out of the router keeps that class focused on
the hot path (resolve) and lets the CLI handle bulk operations without
re-implementing them.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .router import SessionRouter

logger = logging.getLogger(__name__)


class ContinuityManager:
    """Bulk operations on the cross-platform user-link table."""

    def __init__(self, router: SessionRouter) -> None:
        self._router = router

    # ---- bulk binding -------------------------------------------------

    def link_canonical(
        self,
        canonical_user_id: str,
        platform_ids: dict[str, str],
    ) -> None:
        """Register ``canonical_user_id`` against every entry in
        ``platform_ids`` (mapping of platform_name → platform_user_id).

        Atomic: all bindings land in one SQLite transaction so a
        partial failure doesn't leave the user half-linked.

        Idempotent — repeating the call with the same values is a no-op.
        Re-binding a platform_id that already maps to a different
        canonical user overwrites the old binding (consistent with the
        per-row primitive's ``INSERT OR REPLACE`` semantics).
        """
        if not canonical_user_id:
            raise ValueError("canonical_user_id must be non-empty")
        if not platform_ids:
            return

        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()

        db = self._router._db
        try:
            with db:
                db.executemany(
                    "INSERT OR REPLACE INTO gateway_user_links "
                    "(canonical_user_id, platform, platform_user_id, "
                    " created_at) VALUES (?, ?, ?, ?)",
                    [
                        (canonical_user_id, platform, pid, now_iso)
                        for platform, pid in platform_ids.items()
                    ],
                )
        except sqlite3.Error:
            logger.exception(
                "link_canonical failed for %s; rolling back",
                canonical_user_id,
            )
            raise

    def unlink_canonical(self, canonical_user_id: str) -> int:
        """Drop every platform binding for ``canonical_user_id``.

        Returns the number of rows removed.
        """
        if not canonical_user_id:
            return 0
        cur = self._router._db.execute(
            "DELETE FROM gateway_user_links WHERE canonical_user_id = ?",
            (canonical_user_id,),
        )
        self._router._db.commit()
        return cur.rowcount

    # ---- inspection ---------------------------------------------------

    def platforms_for(self, canonical_user_id: str) -> list[tuple[str, str]]:
        """Return every ``(platform, platform_user_id)`` bound to
        ``canonical_user_id``, sorted for stable display."""
        rows = self._router._db.execute(
            "SELECT platform, platform_user_id FROM gateway_user_links "
            "WHERE canonical_user_id = ? "
            "ORDER BY platform ASC, platform_user_id ASC",
            (canonical_user_id,),
        ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def canonical_for(self, platform: str, platform_user_id: str) -> str | None:
        """Reverse lookup: which canonical user owns this platform id?"""
        return self._router._canonical_user(platform, platform_user_id)

    def list_canonical_users(self) -> list[str]:
        """Every distinct canonical user across the table."""
        rows = self._router._db.execute(
            "SELECT DISTINCT canonical_user_id FROM gateway_user_links ORDER BY canonical_user_id"
        ).fetchall()
        return [row[0] for row in rows]
