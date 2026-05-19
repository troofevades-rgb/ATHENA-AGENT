"""CronJob dataclass — persistent record for a scheduled job.

Jobs are persisted in a SQLite database next to APScheduler's jobstore, so
the CLI can list and edit them without touching the scheduler. The
scheduler reads job IDs from this table at startup and re-registers them
with the APScheduler instance.

Two modes:
- ``agent``: full LLM-driven turn, optionally seeded with a skill or prompt.
- ``watchdog``: fixed shell script invocation; no LLM at all. Cheap and
  predictable — for sentinel checks that should not consume tokens.

Delivery routes the job's output to ``log``, ``file:<path>``, or
``gateway://<platform>/<chat_id>`` (the gateway path is a Phase 10 hook;
for now it logs a warning).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_VALID_MODES = ("agent", "watchdog")


@dataclass
class CronJob:
    """One scheduled cron job. ``id`` is stable and used as the
    APScheduler job ID, so a CRUD round-trip survives daemon restarts.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    cron_expr: str = ""
    mode: str = "agent"
    description: str = ""
    skill: str | None = None
    prompt: str | None = None
    script: str | None = None
    delivery_target: str = "log"
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_run_at: datetime | None = None
    last_status: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in _VALID_MODES:
            raise ValueError(f"invalid cron mode {self.mode!r}; must be one of {_VALID_MODES}")
        if self.mode == "watchdog" and not self.script:
            raise ValueError("watchdog mode requires a script")
        if self.mode == "agent" and not (self.skill or self.prompt):
            raise ValueError("agent mode requires either a skill or a prompt")

    # ---- JSON serialization ----

    def to_dict(self) -> dict:
        d = asdict(self)
        for key in ("created_at", "last_run_at"):
            v = d.get(key)
            if isinstance(v, datetime):
                d[key] = v.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> CronJob:
        kwargs = dict(d)
        for key in ("created_at", "last_run_at"):
            v = kwargs.get(key)
            if isinstance(v, str):
                try:
                    kwargs[key] = datetime.fromisoformat(v)
                except ValueError:
                    kwargs[key] = None
        if kwargs.get("created_at") is None:
            kwargs["created_at"] = datetime.now(timezone.utc)
        return cls(**kwargs)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> CronJob:
        return cls.from_dict(json.loads(s))


# ---- Persistence ---------------------------------------------------------


class JobStore:
    """SQLite-backed CronJob store. Keeps job metadata next to the
    APScheduler jobstore so the CLI doesn't need to ask the scheduler.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cron_jobs (
                    id              TEXT PRIMARY KEY,
                    cron_expr       TEXT NOT NULL,
                    mode            TEXT NOT NULL,
                    description     TEXT NOT NULL DEFAULT '',
                    skill           TEXT,
                    prompt          TEXT,
                    script          TEXT,
                    delivery_target TEXT NOT NULL DEFAULT 'log',
                    enabled         INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT NOT NULL,
                    last_run_at     TEXT,
                    last_status     TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert(self, job: CronJob) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO cron_jobs(
                    id, cron_expr, mode, description, skill, prompt, script,
                    delivery_target, enabled, created_at, last_run_at, last_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    cron_expr = excluded.cron_expr,
                    mode = excluded.mode,
                    description = excluded.description,
                    skill = excluded.skill,
                    prompt = excluded.prompt,
                    script = excluded.script,
                    delivery_target = excluded.delivery_target,
                    enabled = excluded.enabled,
                    last_run_at = excluded.last_run_at,
                    last_status = excluded.last_status
                """,
                (
                    job.id,
                    job.cron_expr,
                    job.mode,
                    job.description,
                    job.skill,
                    job.prompt,
                    job.script,
                    job.delivery_target,
                    1 if job.enabled else 0,
                    job.created_at.isoformat(),
                    job.last_run_at.isoformat() if job.last_run_at else None,
                    job.last_status,
                ),
            )

    def get(self, job_id: str) -> CronJob | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM cron_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self) -> list[CronJob]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM cron_jobs ORDER BY created_at").fetchall()
        return [self._row_to_job(r) for r in rows]

    def delete(self, job_id: str) -> bool:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
            return cur.rowcount > 0

    def record_run(self, job_id: str, *, status: str, when: datetime | None = None) -> None:
        when = when or datetime.now(timezone.utc)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE cron_jobs SET last_run_at = ?, last_status = ? WHERE id = ?",
                (when.isoformat(), status, job_id),
            )

    def _row_to_job(self, row: sqlite3.Row) -> CronJob:
        def _parse_iso(s: str | None) -> datetime | None:
            if not s:
                return None
            try:
                return datetime.fromisoformat(s)
            except ValueError:
                return None

        created = _parse_iso(row["created_at"]) or datetime.now(timezone.utc)
        return CronJob(
            id=row["id"],
            cron_expr=row["cron_expr"],
            mode=row["mode"],
            description=row["description"],
            skill=row["skill"],
            prompt=row["prompt"],
            script=row["script"],
            delivery_target=row["delivery_target"],
            enabled=bool(row["enabled"]),
            created_at=created,
            last_run_at=_parse_iso(row["last_run_at"]),
            last_status=row["last_status"],
        )
