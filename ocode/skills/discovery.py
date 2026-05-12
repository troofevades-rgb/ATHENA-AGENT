"""Skill discovery — walks search paths, builds the catalog.

Two search paths: ``~/.ocode/skills/`` (user-global) and
``<workspace>/.ocode/skills/`` (workspace-local). Workspace wins on name
collision, since later iteration overrides earlier in the result dict.

A skill is a *directory* containing a ``SKILL.md``. Loose files and
directories without a SKILL.md are ignored. Malformed SKILL.md files are
skipped with a warning rather than crashing discovery.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .frontmatter import FrontmatterError, SkillFrontmatter, parse_frontmatter

logger = logging.getLogger(__name__)


def search_paths(workspace: Path | None = None) -> list[Path]:
    """User skills first, then workspace skills. Only existing dirs returned."""
    paths = [Path.home() / ".ocode" / "skills"]
    if workspace is not None:
        paths.append(workspace / ".ocode" / "skills")
    return [p for p in paths if p.exists()]


def _scan_dir(base: Path, *, include_archived: bool) -> dict[str, tuple[SkillFrontmatter, Path]]:
    found: dict[str, tuple[SkillFrontmatter, Path]] = {}
    archive_dir = base / ".archive"

    # First pass: regular skills directly under base.
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue  # .archive handled separately; other dotdirs are noise
        fm = _try_parse(entry)
        if fm is None:
            continue
        if fm.state == "archived" and not include_archived:
            continue
        found[fm.name] = (fm, entry)

    # Second pass: archived skills under .archive/.
    if include_archived and archive_dir.exists() and archive_dir.is_dir():
        for entry in archive_dir.iterdir():
            if not entry.is_dir():
                continue
            fm = _try_parse(entry)
            if fm is None:
                continue
            # Archived skills overlay their non-archived sibling only if the
            # sibling wasn't already discovered.
            found.setdefault(fm.name, (fm, entry))

    return found


def _try_parse(skill_dir: Path) -> SkillFrontmatter | None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    try:
        result = parse_frontmatter(skill_md)
    except FrontmatterError as e:
        logger.warning("skipping malformed skill %s: %s", skill_dir, e)
        return None
    if result is None:
        return None
    fm, _body = result
    return fm


def discover_skills(
    workspace: Path | None = None,
    *,
    include_archived: bool = False,
) -> dict[str, tuple[SkillFrontmatter, Path]]:
    """Walk search paths and return ``{name: (frontmatter, skill_dir)}``.

    Workspace entries override user entries on name collision (workspace
    iterates last, overwriting). Archived skills are only included when
    ``include_archived=True`` and live under ``<base>/.archive/<name>/``.
    """
    found: dict[str, tuple[SkillFrontmatter, Path]] = {}
    for base in search_paths(workspace):
        found.update(_scan_dir(base, include_archived=include_archived))
    return found
