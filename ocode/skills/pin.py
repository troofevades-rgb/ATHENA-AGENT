"""Pin/unpin a skill. Pinned skills bypass auto-archive and curator-driven
consolidation regardless of last_activity_at — the state machine and curator
both honor the flag."""
from __future__ import annotations

from pathlib import Path

from .archive import SkillNotFoundError
from .discovery import discover_skills
from .frontmatter import parse_frontmatter, serialize_frontmatter
from . import loader


def _set_pinned(name: str, value: bool, workspace: Path | None) -> Path:
    skills = discover_skills(workspace, include_archived=True)
    entry = skills.get(name)
    if entry is None:
        raise SkillNotFoundError(f"no skill named {name!r}")
    _fm, skill_dir = entry
    skill_md = skill_dir / "SKILL.md"
    fm, body = parse_frontmatter(skill_md)
    fm.pinned = value
    skill_md.write_text(serialize_frontmatter(fm, body), encoding="utf-8")
    loader.invalidate(name, workspace)
    return skill_dir


def pin_skill(name: str, workspace: Path | None = None) -> Path:
    """Idempotent — pinning an already-pinned skill is a no-op (same frontmatter
    is re-written, but it's stable since serialization is deterministic)."""
    return _set_pinned(name, True, workspace)


def unpin_skill(name: str, workspace: Path | None = None) -> Path:
    return _set_pinned(name, False, workspace)
