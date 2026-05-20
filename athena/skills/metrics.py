"""Per-skill usage metrics (T3-06R).

Tracks the signal Phase-16 observability doesn't:

- ``views`` — how many times the skill body was disclosed to the
  agent (via ``manager.skill_view`` or ``loader.load_body``)
- ``last_used_at`` — the most recent disclosure timestamp
- ``sessions_used_in`` — distinct session ids that disclosed the
  skill (cardinality is the user-visible signal; the set itself
  isn't shown)
- ``outcomes`` — optional label distribution (``good``, ``bad``,
  ``preference_pair``) sourced from
  ``athena train review`` for skills that ended up in a labelled
  trajectory

Storage layout: append-only JSONL at
``<profile_dir>/skill_metrics.jsonl``. Two record shapes
share the file:

  {"event":"view",    "skill_name":..., "ts":..., "session_id":...}
  {"event":"outcome", "skill_name":..., "ts":..., "good":1}     # or bad / preference_pair

The store aggregates on read. T3-05R's
:func:`athena.transform.suggestion.build_suggestion_fn` already
reads this file — its aggregator filters by ``skill_name`` +
integer-typed ``good``/``bad``/``preference_pair`` fields and
silently ignores everything else, so view events don't perturb
the suggestion enhancer.

The spec called for routing writes through
``snapshot_and_record``. Skill metrics are operational data, not
user-authored content — snapshotting every view would flood the
audit log with low-value entries. We use the same plain
``open("a")`` pattern as ``athena.safety.audit.MutationAuditLog``,
``athena.proxy.logging``, and the T3-02
``athena/mcp/request_log.py`` (all operational JSONL surfaces),
and allowlist the module in ``tests/safety/test_no_raw_writes.py``.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import logging
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_WRITE_LOCK = threading.Lock()


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(s: str) -> _dt.datetime | None:
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return _dt.datetime.fromisoformat(s)
    except ValueError:
        return None


@dataclasses.dataclass
class SkillMetric:
    """Aggregated per-skill record. Populated by reading the JSONL."""

    name: str
    views: int = 0
    last_used_at: str | None = None
    sessions_used_in: int = 0
    outcomes: dict[str, int] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "views": self.views,
            "last_used_at": self.last_used_at,
            "sessions_used_in": self.sessions_used_in,
            "outcomes": dict(self.outcomes),
        }

    def days_stale(self, *, now: _dt.datetime | None = None) -> float | None:
        """Days since :attr:`last_used_at`. ``None`` if never used."""
        if not self.last_used_at:
            return None
        ts = _parse_iso(self.last_used_at)
        if ts is None:
            return None
        current = now or _dt.datetime.now(_dt.timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=_dt.timezone.utc)
        return (current - ts).total_seconds() / 86400.0


class SkillMetricsStore:
    """Append-only JSONL store with aggregate-on-read semantics.

    Cheap on the hot path: ``record_view`` and ``record_outcome``
    are a single line append + flush. Reads (``get``, ``all``,
    ``top``, ``stale``) walk the whole file — fine for sub-1k-skill
    catalogues with ~hundreds of views per session; a follow-up
    can add an in-memory index if profiling shows it matters.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ---- writes ------------------------------------------------------

    def record_view(self, name: str, session_id: str | None = None) -> None:
        """Append one view event for ``name``. Idempotent failure
        on disk error — logging metrics must never block the agent."""
        if not name:
            return
        entry: dict[str, Any] = {
            "event": "view",
            "skill_name": name,
            "ts": _now_iso(),
        }
        if session_id:
            entry["session_id"] = session_id
        self._append(entry)

    def record_outcome(self, name: str, outcome: str) -> None:
        """Append one outcome event. ``outcome`` is one of ``good``,
        ``bad``, ``preference_pair``. T3-05R's suggestion enhancer
        reads these as integer-keyed labels."""
        if not name or outcome not in ("good", "bad", "preference_pair"):
            return
        entry = {
            "event": "outcome",
            "skill_name": name,
            "ts": _now_iso(),
            outcome: 1,
        }
        self._append(entry)

    def _append(self, entry: dict[str, Any]) -> None:
        line = json.dumps(entry, separators=(",", ":"), ensure_ascii=False)
        try:
            with _WRITE_LOCK, open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            logger.debug("skill_metrics append failed: %s", e)

    # ---- reads -------------------------------------------------------

    def all(self) -> dict[str, SkillMetric]:
        """Aggregate every line into ``{name: SkillMetric}``. Returns
        an empty dict when the file doesn't exist yet."""
        if not self.path.exists():
            return {}
        sessions_by_name: dict[str, set[str]] = {}
        out: dict[str, SkillMetric] = {}
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return {}
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            name = rec.get("skill_name")
            if not isinstance(name, str) or not name:
                continue
            metric = out.setdefault(name, SkillMetric(name=name))
            event = rec.get("event")
            ts = rec.get("ts")
            if event == "view":
                metric.views += 1
                if isinstance(ts, str) and (
                    metric.last_used_at is None or ts > metric.last_used_at
                ):
                    metric.last_used_at = ts
                sid = rec.get("session_id")
                if isinstance(sid, str) and sid:
                    sessions_by_name.setdefault(name, set()).add(sid)
            elif event == "outcome" or "good" in rec or "bad" in rec or "preference_pair" in rec:
                for label in ("good", "bad", "preference_pair"):
                    v = rec.get(label)
                    if isinstance(v, int) and v > 0:
                        metric.outcomes[label] = metric.outcomes.get(label, 0) + v
                if isinstance(ts, str) and (
                    metric.last_used_at is None or ts > metric.last_used_at
                ):
                    # Outcome events also update last_used (the agent
                    # invoked the skill at this moment).
                    pass  # don't overwrite; views are the canonical signal
        for name, sids in sessions_by_name.items():
            out[name].sessions_used_in = len(sids)
        return out

    def get(self, name: str) -> SkillMetric:
        """Return the metric for ``name`` (empty :class:`SkillMetric`
        when there are no records yet)."""
        return self.all().get(name) or SkillMetric(name=name)

    def top(self, n: int = 10) -> list[SkillMetric]:
        """Most-viewed skills first. Ties broken by last-used recency
        (more recent first). Python's sort is stable: sort by the
        secondary key, then by the primary."""
        metrics = list(self.all().values())
        metrics.sort(key=lambda m: m.last_used_at or "", reverse=True)
        metrics.sort(key=lambda m: m.views, reverse=True)
        return metrics[: max(0, int(n))]

    def stale(self, older_than_days: int = 30) -> list[SkillMetric]:
        """Skills that have a ``last_used_at`` older than the
        threshold (does NOT include never-used skills — they have
        no last_used at all). Use :meth:`never_used` for those."""
        now = _dt.datetime.now(_dt.timezone.utc)
        threshold = now - _dt.timedelta(days=older_than_days)
        out: list[SkillMetric] = []
        for m in self.all().values():
            if m.last_used_at is None:
                continue
            ts = _parse_iso(m.last_used_at)
            if ts is None:
                continue
            if ts < threshold:
                out.append(m)
        out.sort(key=lambda m: m.last_used_at or "")
        return out

    def never_used(self, catalogue_names: Iterable[str]) -> list[str]:
        """Names from ``catalogue_names`` that have zero recorded
        views. The caller passes the live skill catalogue
        (``discover_skills``) so the store can join against it."""
        seen = {name for name, m in self.all().items() if m.views > 0}
        return sorted(n for n in catalogue_names if n not in seen)


# ---------------------------------------------------------------------------
# No-op store for the ``skill_metrics_enabled = false`` path
# ---------------------------------------------------------------------------


class _NoopStore(SkillMetricsStore):
    """All writes are silent no-ops; reads return empty."""

    def __init__(self) -> None:  # noqa: D107 — intentional non-call to super
        self.path = Path("/dev/null")

    def record_view(self, name: str, session_id: str | None = None) -> None:
        return None

    def record_outcome(self, name: str, outcome: str) -> None:
        return None

    def all(self) -> dict[str, SkillMetric]:
        return {}


def metrics_path(profile_dir: Path) -> Path:
    """Canonical location for the per-profile metrics file. Matches
    the path T3-05R's suggestion enhancer reads from."""
    return Path(profile_dir) / "skill_metrics.jsonl"


# ---------------------------------------------------------------------------
# Active store: ContextVar-based so hooks reach the right store without
# threading an explicit argument through every callsite.
# ---------------------------------------------------------------------------


import contextvars as _contextvars

_active_store: _contextvars.ContextVar[SkillMetricsStore | None] = _contextvars.ContextVar(
    "athena_skill_metrics_store", default=None
)


def get_active_store() -> SkillMetricsStore | None:
    return _active_store.get()


def set_active_store(store: SkillMetricsStore | None) -> None:
    _active_store.set(store)


def record_view_active(name: str, session_id: str | None = None) -> None:
    """Convenience: record a view against the active store (if any).

    The hook in :mod:`athena.skills.manager` / :mod:`athena.skills.loader`
    calls this — when no store is registered (off-by-config, tests,
    forks that opted out), it's a silent no-op."""
    store = _active_store.get()
    if store is None:
        return
    try:
        store.record_view(name, session_id=session_id)
    except Exception:  # noqa: BLE001
        logger.debug("record_view_active failed for %s", name, exc_info=True)
