"""Move skill directories into and out of ``<base>/.archive/``.

Archive is destructive only in the sense that the directory moves; the
content is preserved and reachable via ``discover_skills(include_archived=True)``.
Both operations are idempotent in the soft sense — if the target name
already exists at the destination, a numeric suffix (``-1``, ``-2``, …) is
appended so no data is overwritten.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import loader
from .discovery import discover_skills
from .frontmatter import parse_frontmatter, serialize_frontmatter


class SkillNotFoundError(LookupError):
    pass


def _resolve_unique(parent: Path, name: str) -> Path:
    """Find a non-colliding directory name under ``parent``. Returns the
    chosen path (NOT yet created on disk)."""
    candidate = parent / name
    if not candidate.exists():
        return candidate
    n = 1
    while True:
        candidate = parent / f"{name}-{n}"
        if not candidate.exists():
            return candidate
        n += 1


def _patch_state(skill_md: Path, new_state: str) -> None:
    """Rewrite a SKILL.md's frontmatter ``state`` field in place."""
    parsed = parse_frontmatter(skill_md)
    if parsed is None:
        raise SkillNotFoundError(f"no SKILL.md to patch at {skill_md}")
    fm, body = parsed
    fm.state = new_state
    skill_md.write_text(serialize_frontmatter(fm, body), encoding="utf-8")


def archive_skill(name: str, workspace: Path | None = None) -> Path:
    """Move ``<base>/<name>/`` to ``<base>/.archive/<name>/`` and set
    ``state=archived``. Returns the new path.

    Raises :class:`SkillNotFoundError` if no active skill of that name exists.

    Atomic against a frontmatter-write failure: if ``_patch_state``
    raises after the directory move, the move is reversed so the
    catalog doesn't end up with a skill living in ``.archive/``
    whose frontmatter still says ``state=active`` (invisible to
    default ``discover_skills`` and confusing to anyone running
    ``include_archived=True``).
    """
    skills = discover_skills(workspace, include_archived=False)
    entry = skills.get(name)
    if entry is None:
        raise SkillNotFoundError(f"no active skill named {name!r}")
    _fm, src = entry
    base = src.parent
    archive_dir = base / ".archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = _resolve_unique(archive_dir, name)
    shutil.move(str(src), str(dest))
    try:
        _patch_state(dest / "SKILL.md", "archived")
    except Exception:
        # Frontmatter write failed; undo the move so the catalog
        # invariant holds (dir location matches state value).
        try:
            shutil.move(str(dest), str(src))
        except OSError:
            pass
        raise
    loader.invalidate(name, workspace)
    return dest


def unarchive_skill(name: str, workspace: Path | None = None) -> Path:
    """Move ``<base>/.archive/<name>/`` back up to ``<base>/<name>/`` and set
    ``state=active``. Returns the new path.

    Atomic against a frontmatter-write failure: see :func:`archive_skill`."""
    skills = discover_skills(workspace, include_archived=True)
    entry = skills.get(name)
    if entry is None:
        raise SkillNotFoundError(f"no skill named {name!r}")
    _fm, src = entry
    # Must currently live under .archive/.
    if src.parent.name != ".archive":
        raise SkillNotFoundError(f"skill {name!r} is not archived")
    base = src.parent.parent
    dest = _resolve_unique(base, name)
    shutil.move(str(src), str(dest))
    try:
        _patch_state(dest / "SKILL.md", "active")
    except Exception:
        try:
            shutil.move(str(dest), str(src))
        except OSError:
            pass
        raise
    loader.invalidate(name, workspace)
    return dest
