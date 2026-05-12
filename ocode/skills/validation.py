"""Skill validator. Returns a list of human-readable error strings; empty
list means valid.

Used by ``ocode skills validate`` (CLI) and by the importer's post-import
checks. Keeps validation out of the parser so callers that just want to
read can do so without paying the validation cost twice.
"""
from __future__ import annotations

from pathlib import Path

from .frontmatter import FrontmatterError, parse_frontmatter


def validate_skill(skill_dir: Path) -> list[str]:
    """Return a list of validation problems for the skill at ``skill_dir``."""
    errors: list[str] = []
    if not skill_dir.is_dir():
        return [f"not a directory: {skill_dir}"]

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return [f"missing SKILL.md in {skill_dir}"]

    try:
        result = parse_frontmatter(skill_md)
    except FrontmatterError as e:
        return [f"frontmatter: {e}"]
    if result is None:
        return [f"could not read {skill_md}"]
    fm, _body = result

    # parse_frontmatter already validates name regex and description length;
    # we just confirm presence so callers know the parse succeeded fully.
    if not fm.name:
        errors.append("name missing")
    if not fm.description:
        errors.append("description missing")
    if fm.state not in ("active", "stale", "archived"):
        errors.append(f"invalid state {fm.state!r}")
    if fm.write_origin not in (
        "foreground", "background_review", "curator", "migration", "system"
    ):
        errors.append(f"invalid write_origin {fm.write_origin!r}")

    return errors
