"""Map Hermes skills into ocode v2 skill directories.

Hermes uses the same agentskills.io-rooted format we do, plus a handful of
extra frontmatter fields (author, platforms, etc.) that pass through to
``metadata``. The mapper:

1. Walks ``<source>/skills/<name>/`` (and ``<source>/skills/.archive/<name>/``).
2. Reads each ``SKILL.md`` with a *permissive* YAML loader — missing fields
   are tolerated, since older Hermes versions were lax about them.
3. Rebuilds frontmatter with ``write_origin="migration"`` and
   ``imported_at=now``; copies original ``created_at`` / ``last_activity_at``
   when present, falls back to the file's mtime otherwise.
4. Copies the skill directory into the destination (rewriting only
   ``SKILL.md``; ``references/``, ``templates/``, and ``scripts/`` carry
   over unchanged).
5. Skips destinations that already exist with ``write_origin="migration"``
   (prior migrations are idempotent). Other collisions are renamed
   ``<name>-from-hermes``.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..skills.frontmatter import (
    SkillFrontmatter,
    parse_frontmatter,
    serialize_frontmatter,
    FrontmatterError,
)
from .report import Report


_FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)

# agentskills.io standard fields we hoist directly onto the dataclass.
_PASSTHROUGH = ("description", "version", "license", "compatibility")
# Hermes-specific fields that survive in metadata.
_HERMES_METADATA_KEYS = ("author", "platforms", "tags", "category")


def _read_hermes(skill_md: Path) -> tuple[dict[str, Any], str]:
    """Permissive parse: returns (raw_dict, body)."""
    raw = skill_md.read_text(encoding="utf-8")
    m = _FM_RE.match(raw)
    if not m:
        raise FrontmatterError(f"no YAML frontmatter in {skill_md}")
    data = yaml.safe_load(m.group(1)) or {}
    if not isinstance(data, dict):
        raise FrontmatterError(f"frontmatter must be a mapping in {skill_md}")
    return data, m.group(2)


def _ocode_frontmatter_from_hermes(
    hermes: dict[str, Any],
    *,
    hermes_path: Path,
    is_archived: bool,
    imported_at: datetime,
) -> SkillFrontmatter:
    name = str(hermes.get("name") or hermes_path.name)
    description = str(hermes.get("description") or "")
    metadata = dict(hermes.get("metadata") or {})
    for key in _HERMES_METADATA_KEYS:
        if key in hermes and key not in metadata:
            metadata[key] = hermes[key]

    fm_kwargs: dict[str, Any] = {
        "name": name,
        "description": description,
        "metadata": metadata,
        "state": "archived" if is_archived else "active",
        "pinned": False,
        "write_origin": "migration",
        "source_hermes_path": str(hermes_path),
        "imported_at": imported_at,
    }
    for key in _PASSTHROUGH:
        if key == "description":
            continue
        if hermes.get(key):
            fm_kwargs[key] = hermes[key]

    mtime = datetime.fromtimestamp(hermes_path.stat().st_mtime, tz=timezone.utc)
    fm_kwargs["created_at"] = _coerce_dt(hermes.get("created_at")) or mtime
    fm_kwargs["last_activity_at"] = _coerce_dt(hermes.get("last_activity_at")) or mtime

    # use_count may come from a parallel .skill_usage db; for now just take
    # whatever the file frontmatter claims, defaulting to 0.
    use_count = hermes.get("use_count", 0)
    try:
        fm_kwargs["use_count"] = int(use_count)
    except (TypeError, ValueError):
        fm_kwargs["use_count"] = 0

    return SkillFrontmatter(**fm_kwargs)


def _coerce_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.rstrip("Z")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _copy_skill_dir(src: Path, dest: Path, *, new_fm: SkillFrontmatter, body: str, dry_run: bool) -> None:
    if dry_run:
        return
    shutil.copytree(src, dest)
    (dest / "SKILL.md").write_text(
        serialize_frontmatter(new_fm, body), encoding="utf-8"
    )


def _existing_origin(skill_md: Path) -> str | None:
    if not skill_md.exists():
        return None
    try:
        parsed = parse_frontmatter(skill_md)
    except FrontmatterError:
        return None
    if parsed is None:
        return None
    return parsed[0].write_origin


def _iter_source_skills(source: Path) -> list[tuple[Path, bool]]:
    out: list[tuple[Path, bool]] = []
    skills_root = source / "skills"
    if not skills_root.exists():
        return out
    for entry in skills_root.iterdir():
        if entry.is_dir() and entry.name != ".archive" and not entry.name.startswith("."):
            out.append((entry, False))
    archive_root = skills_root / ".archive"
    if archive_root.exists():
        for entry in archive_root.iterdir():
            if entry.is_dir():
                out.append((entry, True))
    return out


def _resolve_destination(
    base: Path,
    name: str,
    *,
    is_archived: bool,
    report: Report,
    hermes_path: Path,
    dry_run: bool,
) -> tuple[Path, str] | None:
    """Return (dest_path, mode) where mode is 'imported' or 'conflict_renamed',
    or None if the existing destination is a prior migration (skip)."""
    target_root = base / ".archive" if is_archived else base
    if not dry_run:
        target_root.mkdir(parents=True, exist_ok=True)
    candidate = target_root / name
    if candidate.exists():
        origin = _existing_origin(candidate / "SKILL.md")
        if origin == "migration":
            report.add("skipped_prior_migration", {
                "name": name,
                "destination": str(candidate),
                "source": str(hermes_path),
            })
            return None
        # Real conflict — rename with -from-hermes suffix.
        renamed = target_root / f"{name}-from-hermes"
        n = 1
        while renamed.exists():
            n += 1
            renamed = target_root / f"{name}-from-hermes-{n}"
        report.add("conflict_renamed", {
            "original": name,
            "imported_as": renamed.name,
            "source": str(hermes_path),
        })
        return renamed, "conflict_renamed"
    return candidate, "imported"


def import_skills(
    source: Path,
    dest: Path,
    *,
    profile: str = "default",
    report: Report,
    dry_run: bool = False,
) -> None:
    """Map every skill under ``<source>/skills/`` into ``<dest>/skills/``.

    ``profile`` is reserved for future per-profile installs (Phase 1
    skills live at the user level, not per-profile, so we don't honor it yet
    — recorded in the report for traceability).
    """
    imported_at = datetime.now(timezone.utc)
    base = dest / "skills"
    for hermes_path, is_archived in _iter_source_skills(source):
        skill_md = hermes_path / "SKILL.md"
        if not skill_md.exists():
            report.add("skipped_no_skill_md", {"source": str(hermes_path)})
            continue
        try:
            hermes_data, body = _read_hermes(skill_md)
        except FrontmatterError as e:
            report.add("skipped_malformed", {"source": str(hermes_path), "error": str(e)})
            continue

        try:
            new_fm = _ocode_frontmatter_from_hermes(
                hermes_data,
                hermes_path=hermes_path,
                is_archived=is_archived,
                imported_at=imported_at,
            )
        except FrontmatterError as e:
            report.add("skipped_unmappable", {"source": str(hermes_path), "error": str(e)})
            continue

        resolved = _resolve_destination(
            base, new_fm.name,
            is_archived=is_archived,
            report=report,
            hermes_path=hermes_path,
            dry_run=dry_run,
        )
        if resolved is None:
            continue
        dest_path, mode = resolved
        # If we renamed due to conflict, propagate the chosen dir name into
        # the frontmatter so the skill round-trips correctly via discovery.
        if mode == "conflict_renamed":
            new_fm.name = dest_path.name

        _copy_skill_dir(hermes_path, dest_path, new_fm=new_fm, body=body, dry_run=dry_run)
        report.add("imported_skill", {
            "name": new_fm.name,
            "source": str(hermes_path),
            "destination": str(dest_path),
            "state": new_fm.state,
            "profile": profile,
            "dry_run": dry_run,
        })
