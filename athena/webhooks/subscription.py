"""WebhookSubscription dataclass + SQLite store.

One row per registered webhook. The schema is deliberately flat —
webhooks rarely need joins or aggregations beyond "list mine" and
"get by id," and a single table keeps the migration story trivial.

Auth secrets are stored plaintext. The same threat model that
applies to ``credentials.json`` and ``mcp_tokens/`` applies here:
filesystem permissions on the profile directory are the boundary.
A user able to read ``webhooks.db`` already has access to every
other secret on disk. Building a real key-derivation flow for one
table buys nothing against that adversary and adds operational
complexity (rotation, master-key management).
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

AuthType = Literal["hmac_sha256", "bearer", "none"]
BindingType = Literal["skill", "prompt"]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    auth_type TEXT NOT NULL,
    auth_secret TEXT NOT NULL DEFAULT '',
    binding_type TEXT NOT NULL,
    skill_name TEXT,
    prompt_template TEXT,
    delivery_target TEXT NOT NULL DEFAULT 'log',
    rate_limit_per_minute INTEGER NOT NULL DEFAULT 60,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_fired_at TEXT,
    fire_count INTEGER NOT NULL DEFAULT 0
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@dataclass
class WebhookSubscription:
    """One registered webhook.

    ``id`` defaults to a UUID4 — short enough for URLs, opaque
    enough that an attacker can't enumerate.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    auth_type: AuthType = "hmac_sha256"
    auth_secret: str = ""
    binding_type: BindingType = "skill"
    skill_name: str | None = None
    prompt_template: str | None = None
    delivery_target: str = "log"
    rate_limit_per_minute: int = 60
    enabled: bool = True
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    last_fired_at: datetime | None = None
    fire_count: int = 0

    def __post_init__(self) -> None:
        # Validate at construction time — better to fail fast than
        # write garbage to disk.
        if self.auth_type not in ("hmac_sha256", "bearer", "none"):
            raise ValueError(f"invalid auth_type: {self.auth_type!r}")
        if self.binding_type not in ("skill", "prompt"):
            raise ValueError(f"invalid binding_type: {self.binding_type!r}")
        if self.binding_type == "skill" and not self.skill_name:
            raise ValueError("binding_type='skill' requires non-empty skill_name")
        if self.binding_type == "prompt" and not self.prompt_template:
            raise ValueError("binding_type='prompt' requires non-empty prompt_template")
        if self.auth_type != "none" and not self.auth_secret:
            raise ValueError(f"auth_type={self.auth_type!r} requires non-empty auth_secret")
        if self.rate_limit_per_minute < 1:
            raise ValueError(
                f"rate_limit_per_minute must be >= 1, got {self.rate_limit_per_minute}"
            )


class WebhookStore:
    """SQLite persistence for :class:`WebhookSubscription`.

    Lives at ``<profile_dir>/webhooks.db``. Per-profile by design —
    a webhook bound to a skill in profile ``work`` should NOT fire
    when you're running under profile ``personal``.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._db.commit()

    # ---- CRUD ----

    def add(self, sub: WebhookSubscription) -> WebhookSubscription:
        """Insert a new subscription. Raises ``sqlite3.IntegrityError``
        if an id collision occurs (effectively impossible with UUID4)."""
        self._db.execute(
            "INSERT INTO webhook_subscriptions ("
            "id, description, auth_type, auth_secret, binding_type, "
            "skill_name, prompt_template, delivery_target, "
            "rate_limit_per_minute, enabled, created_at, "
            "last_fired_at, fire_count"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sub.id,
                sub.description,
                sub.auth_type,
                sub.auth_secret,
                sub.binding_type,
                sub.skill_name,
                sub.prompt_template,
                sub.delivery_target,
                sub.rate_limit_per_minute,
                1 if sub.enabled else 0,
                sub.created_at.isoformat(),
                sub.last_fired_at.isoformat() if sub.last_fired_at else None,
                sub.fire_count,
            ),
        )
        self._db.commit()
        return sub

    def get(self, id: str) -> WebhookSubscription | None:
        row = self._db.execute(
            "SELECT * FROM webhook_subscriptions WHERE id = ?",
            (id,),
        ).fetchone()
        return _from_row(row) if row else None

    def list(self) -> list[WebhookSubscription]:
        rows = self._db.execute(
            "SELECT * FROM webhook_subscriptions ORDER BY created_at"
        ).fetchall()
        return [_from_row(r) for r in rows]

    def update(self, sub: WebhookSubscription) -> bool:
        cur = self._db.execute(
            "UPDATE webhook_subscriptions SET "
            "description=?, auth_type=?, auth_secret=?, binding_type=?, "
            "skill_name=?, prompt_template=?, delivery_target=?, "
            "rate_limit_per_minute=?, enabled=? "
            "WHERE id=?",
            (
                sub.description,
                sub.auth_type,
                sub.auth_secret,
                sub.binding_type,
                sub.skill_name,
                sub.prompt_template,
                sub.delivery_target,
                sub.rate_limit_per_minute,
                1 if sub.enabled else 0,
                sub.id,
            ),
        )
        self._db.commit()
        return cur.rowcount > 0

    def delete(self, id: str) -> bool:
        cur = self._db.execute(
            "DELETE FROM webhook_subscriptions WHERE id = ?",
            (id,),
        )
        self._db.commit()
        return cur.rowcount > 0

    def set_enabled(self, id: str, enabled: bool) -> bool:
        cur = self._db.execute(
            "UPDATE webhook_subscriptions SET enabled=? WHERE id=?",
            (1 if enabled else 0, id),
        )
        self._db.commit()
        return cur.rowcount > 0

    # ---- bookkeeping ----

    def record_fire(self, id: str) -> None:
        """Increment fire_count + stamp last_fired_at. Called by the
        HTTP listener after a successful auth + dispatch handoff."""
        self._db.execute(
            "UPDATE webhook_subscriptions "
            "SET fire_count = fire_count + 1, last_fired_at = ? "
            "WHERE id = ?",
            (_now_iso(), id),
        )
        self._db.commit()

    def close(self) -> None:
        try:
            self._db.close()
        except sqlite3.Error:
            pass


# ---- helpers --------------------------------------------------------


def _from_row(row: tuple[Any, ...]) -> WebhookSubscription:
    (
        id_,
        description,
        auth_type,
        auth_secret,
        binding_type,
        skill_name,
        prompt_template,
        delivery_target,
        rate_limit_per_minute,
        enabled,
        created_at,
        last_fired_at,
        fire_count,
    ) = row
    # Bypass __post_init__ — rows in the DB were validated at insert
    # time, and a corrupted row (e.g. manually edited) shouldn't
    # break list() / get(). Use object.__new__ + dataclass field init
    # via the typical __init__ to keep validation; ``_skip_validate``
    # isn't a thing, so we just construct normally and let any error
    # bubble for the caller to log.
    return WebhookSubscription(
        id=id_,
        description=description,
        auth_type=auth_type,
        auth_secret=auth_secret,
        binding_type=binding_type,
        skill_name=skill_name,
        prompt_template=prompt_template,
        delivery_target=delivery_target,
        rate_limit_per_minute=rate_limit_per_minute,
        enabled=bool(enabled),
        created_at=(_parse_iso(created_at) or datetime.now(timezone.utc)),
        last_fired_at=_parse_iso(last_fired_at),
        fire_count=fire_count,
    )
