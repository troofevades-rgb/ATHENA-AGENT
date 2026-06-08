"""Seed athena's bundled default skills into the user's skills dir on
first run.

Why: skill discovery reads ``~/.athena/skills/`` (+ a workspace dir), and
a fresh install has an empty ``~/.athena/skills/`` — so a brand-new machine
(or a wheel install, where the repo's workspace skills aren't on disk at
all) starts with zero skills. This copies the package's bundled defaults
(``athena/skills_default/``) into the user dir so every install begins with
a useful library.

One-shot + idempotent: gated by a sentinel so a default the user later
*deletes* doesn't silently reappear; per-skill, never overwrites an
existing skill directory (your edits win).
"""

from __future__ import annotations

import shutil
from pathlib import Path

_SENTINEL = ".defaults_seeded"


def default_skills_dir() -> Path:
    """The packaged default-skill tree shipped inside the wheel."""
    return Path(__file__).resolve().parent.parent / "skills_default"


def seed_default_skills(skills_root: Path, *, force: bool = False) -> int:
    """Copy bundled default skills into ``skills_root`` (e.g.
    ``~/.athena/skills``) for any that aren't already present.

    Returns the number of skills seeded. Runs once (sentinel-gated) unless
    ``force=True``; never overwrites an existing skill directory. Safe to
    call on every startup — it's a cheap no-op after the first run.
    """
    src = default_skills_dir()
    if not src.is_dir():
        return 0
    sentinel = skills_root / _SENTINEL
    if sentinel.exists() and not force:
        return 0
    skills_root.mkdir(parents=True, exist_ok=True)
    seeded = 0
    for skill in sorted(src.iterdir()):
        if not skill.is_dir() or not (skill / "SKILL.md").exists():
            continue
        dest = skills_root / skill.name
        if dest.exists():
            continue
        try:
            shutil.copytree(skill, dest)
            seeded += 1
        except OSError:
            continue
    try:
        sentinel.write_text("seeded\n", encoding="utf-8")
    except OSError:
        pass
    return seeded
