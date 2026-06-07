"""Deterministic skill lifecycle transitions.

Pure function from (catalog snapshot, now) → set of changes, then a side
effect pass that applies the changes to disk. No LLM, no network. Run at
session start (cheap) or on demand from the curator.

Rules, evaluated per-skill in order (first match wins):

1. ``pinned=True`` → skip
2. ``write_origin`` not in {``background_review``, ``curator``} → skip
3. ``write_origin == "migration"`` AND ``last_activity_at <= imported_at`` → skip
4. ``last_activity_at`` older than ``archive_after_days`` AND
   ``state != "archived"`` → archive (move to ``.archive/``, set state)
5. ``last_activity_at`` older than ``stale_after_days`` AND
   ``state == "active"`` → mark stale
6. ``last_activity_at`` within ``stale_after_days`` AND
   ``state == "stale"`` → reactivate
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import archive as archive_mod
from . import loader
from .discovery import discover_skills
from .frontmatter import parse_frontmatter, serialize_frontmatter

_LIFECYCLE_ORIGINS = frozenset({"background_review", "curator"})


def _age(now: datetime, ts: datetime | None) -> timedelta | None:
    if ts is None:
        return None
    return now - ts.astimezone(timezone.utc)


def _patch_state(skill_dir: Path, new_state: str) -> None:
    skill_md = skill_dir / "SKILL.md"
    parsed = parse_frontmatter(skill_md)
    if parsed is None:
        raise archive_mod.SkillNotFoundError(f"no SKILL.md to patch at {skill_md}")
    fm, body = parsed
    fm.state = new_state
    skill_md.write_text(serialize_frontmatter(fm, body), encoding="utf-8")


def apply_transitions(
    workspace: Path | None = None,
    *,
    now: datetime | None = None,
    stale_after_days: int = 30,
    archive_after_days: int = 90,
) -> dict[str, list[str]]:
    """Walk the catalog, apply lifecycle transitions, return ``{action: names}``.

    Action keys: ``marked_stale``, ``archived``, ``reactivated``. Always
    present (empty lists if nothing changed) so callers don't need to ``.get``.
    """
    now = now or datetime.now(timezone.utc)
    stale_cutoff = timedelta(days=stale_after_days)
    archive_cutoff = timedelta(days=archive_after_days)

    result: dict[str, list[str]] = {
        "marked_stale": [],
        "archived": [],
        "reactivated": [],
    }

    # We pass include_archived=True so an "archived" skill with recent activity
    # could theoretically be reactivated; in practice that path is curator-only.
    skills = discover_skills(workspace, include_archived=True)

    for name, (fm, skill_dir) in skills.items():
        if fm.pinned:
            continue
        if fm.write_origin not in _LIFECYCLE_ORIGINS and fm.write_origin != "migration":
            continue
        if fm.write_origin == "migration":
            if fm.last_activity_at is None or fm.imported_at is None:
                continue
            if fm.last_activity_at <= fm.imported_at:
                continue

        age = _age(now, fm.last_activity_at)
        if age is None:
            continue

        if age > archive_cutoff and fm.state != "archived":
            try:
                archive_mod.archive_skill(name, workspace)
            except archive_mod.SkillNotFoundError:
                continue
            result["archived"].append(name)
            continue

        if age > stale_cutoff and fm.state == "active":
            _patch_state(skill_dir, "stale")
            loader.invalidate(name, workspace)
            result["marked_stale"].append(name)
            continue

        if age <= stale_cutoff and fm.state == "stale":
            _patch_state(skill_dir, "active")
            loader.invalidate(name, workspace)
            result["reactivated"].append(name)
            continue

    return result
