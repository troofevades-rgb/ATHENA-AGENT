"""Canonical write paths for skills.

Every mutation flows through this module so write_origin tagging,
last_activity_at bookkeeping, and loader cache invalidation happen in one
place. ``skill_manage`` (the model-facing tool) is a thin dispatcher over
these functions.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..provenance import (
    BACKGROUND_REVIEW,
    CURATOR,
    FOREGROUND,
    MIGRATION,
    SYSTEM,
    get_current_write_origin,
)
from ..safety.mutation import snapshot_and_record
from . import archive as archive_mod
from . import loader, pin
from .archive import SkillNotFoundError
from .discovery import discover_skills, search_paths
from .frontmatter import (
    FrontmatterError,
    SkillFrontmatter,
    parse_frontmatter,
    serialize_frontmatter,
)


_ALLOWED_FILE_SUBDIRS = ("references", "templates", "scripts")

# Write-origins whose existing skills the curator + background_review are
# *allowed* to mutate. Foreground-authored and pinned skills are off-limits;
# migration-origin skills are conditionally allowed (see _curator_can_modify).
_AUTONOMOUS_MUTABLE_ORIGINS = frozenset({BACKGROUND_REVIEW, CURATOR})


class SkillExistsError(FileExistsError):
    pass


class CuratorPolicyError(PermissionError):
    """Raised when the curator (or background_review) tries to do something
    its policy forbids."""


def _curator_can_modify(target_fm: SkillFrontmatter) -> tuple[bool, str]:
    """Return (allowed, reason) for autonomous mutation of an existing skill.

    Pinned skills and foreground-authored skills are inviolate. Migration-
    origin skills bypass autonomous mutation until they have local activity
    (last_activity_at strictly newer than imported_at).
    """
    if target_fm.pinned:
        return False, f"skill {target_fm.name!r} is pinned"
    if target_fm.write_origin == FOREGROUND:
        return False, f"skill {target_fm.name!r} is foreground-authored"
    if target_fm.write_origin == MIGRATION:
        if (
            target_fm.imported_at is None
            or target_fm.last_activity_at is None
            or target_fm.last_activity_at <= target_fm.imported_at
        ):
            return False, (
                f"skill {target_fm.name!r} was imported and has no local "
                "activity yet; curator must not touch it until the user has used it"
            )
    return True, ""


def _target_base(workspace: Path | None) -> Path:
    """Where new skills are written. Workspace if provided, else user home."""
    if workspace is not None:
        return workspace / ".athena" / "skills"
    return Path.home() / ".athena" / "skills"


def _existing(name: str, workspace: Path | None) -> Path | None:
    skills = discover_skills(workspace, include_archived=True)
    entry = skills.get(name)
    return entry[1] if entry else None


def skill_create(
    name: str,
    frontmatter_dict: dict[str, Any],
    body: str,
    workspace: Path | None = None,
) -> Path:
    """Create a new skill directory and write its SKILL.md.

    The frontmatter's ``name`` is forced to ``name``. ``write_origin``
    defaults to the current context's write origin if not specified;
    ``created_at`` and ``last_activity_at`` default to now.

    The serialized SKILL.md is validated *before* the directory is created
    so a malformed frontmatter doesn't leave an empty dir on disk.
    """
    if _existing(name, workspace) is not None:
        raise SkillExistsError(f"skill {name!r} already exists")

    now = datetime.now(timezone.utc)
    fm_dict = dict(frontmatter_dict)
    fm_dict["name"] = name
    fm_dict.setdefault("description", "")
    fm_dict.setdefault("write_origin", get_current_write_origin())
    fm_dict.setdefault("created_at", now)
    fm_dict.setdefault("last_activity_at", now)

    fm = _build_frontmatter(fm_dict)
    serialized = serialize_frontmatter(fm, body)
    _validate_skill_md(serialized)

    base = _target_base(workspace)
    base.mkdir(parents=True, exist_ok=True)
    skill_dir = base / name
    skill_dir.mkdir()
    # Snapshot+audit: skill_create is the first mutation, so the
    # pre-state is an empty dir. The audit record links the new
    # SKILL.md to the snapshot that captured the (empty) directory.
    with snapshot_and_record(
        [skill_dir], tool_name="skill_create",
    ) as ctx:
        (skill_dir / "SKILL.md").write_text(serialized, encoding="utf-8")
        ctx.record(skill_dir / "SKILL.md")
    loader.invalidate(name, workspace)
    return skill_dir


def skill_patch(
    name: str,
    *,
    body: str | None = None,
    frontmatter_updates: dict[str, Any] | None = None,
    workspace: Path | None = None,
) -> Path:
    """Update body and/or frontmatter fields. Preserves anything not touched.

    ``last_activity_at`` is set to now unless the current origin is
    ``system`` (so internal lifecycle moves don't masquerade as user
    activity).

    The new SKILL.md is validated *before* it overwrites the old one; if
    validation fails the existing file is untouched.
    """
    skill_dir = _existing(name, workspace)
    if skill_dir is None:
        raise SkillNotFoundError(f"no skill named {name!r}")
    skill_md = skill_dir / "SKILL.md"
    existing_fm, existing_body = parse_frontmatter(skill_md)

    origin = get_current_write_origin()
    if origin in _AUTONOMOUS_MUTABLE_ORIGINS:
        allowed, reason = _curator_can_modify(existing_fm)
        if not allowed:
            raise CuratorPolicyError(reason)

    updated = _frontmatter_to_dict(existing_fm)
    if frontmatter_updates:
        updated.update(frontmatter_updates)
        # Name cannot be changed via patch — that would invalidate the dir name.
        updated["name"] = existing_fm.name
    if origin != SYSTEM:
        updated["last_activity_at"] = datetime.now(timezone.utc)

    new_fm = _build_frontmatter(updated)
    new_body = existing_body if body is None else body
    serialized = serialize_frontmatter(new_fm, new_body)
    _validate_skill_md(serialized)

    with snapshot_and_record(
        [skill_dir], tool_name="skill_patch",
    ) as ctx:
        skill_md.write_text(serialized, encoding="utf-8")
        ctx.record(skill_md)
    loader.invalidate(name, workspace)
    return skill_dir


def skill_delete(
    name: str,
    workspace: Path | None = None,
    absorbed_into: str | None = None,
) -> Path:
    """Soft-delete by archiving. Curator and background_review must both pass
    ``absorbed_into`` (a skill name, or the literal empty string meaning a
    true prune). Foreground origin may pass it or not.

    Autonomous origins additionally cannot delete foreground / pinned / not-
    yet-locally-active migration skills — see :func:`_curator_can_modify`.
    """
    origin = get_current_write_origin()
    if origin in _AUTONOMOUS_MUTABLE_ORIGINS:
        if absorbed_into is None:
            raise CuratorPolicyError(
                f"{origin} must pass absorbed_into (skill name or empty string)"
            )
        # Inspect the target skill's frontmatter before archiving so we can
        # refuse on policy without leaving the workspace mid-mutated.
        skills = discover_skills(workspace, include_archived=False)
        entry = skills.get(name)
        if entry is not None:
            target_fm, _ = entry
            allowed, reason = _curator_can_modify(target_fm)
            if not allowed:
                raise CuratorPolicyError(reason)
    # Resolve the live skill dir before archiving so we can snapshot
    # its pre-archive state. archive_skill() renames the dir, so the
    # snapshot must capture the source path, not the post-archive path.
    src = _existing(name, workspace)
    snapshot_paths = [src] if src is not None else []
    with snapshot_and_record(
        snapshot_paths, tool_name="skill_delete",
    ) as ctx:
        new_path = archive_mod.archive_skill(name, workspace)
        if absorbed_into is not None:
            meta = {
                "absorbed_into": absorbed_into,
                "archived_at": datetime.now(timezone.utc).isoformat(),
                "origin": origin,
            }
            (new_path / ".archive_meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
        if src is not None:
            ctx.record(src / "SKILL.md")
    return new_path


def skill_unarchive(name: str, workspace: Path | None = None) -> Path:
    return archive_mod.unarchive_skill(name, workspace)


def skill_pin(name: str, workspace: Path | None = None) -> Path:
    """Pin is a foreground-only operation; autonomous origins are refused."""
    if get_current_write_origin() in _AUTONOMOUS_MUTABLE_ORIGINS:
        raise CuratorPolicyError("pin is a foreground-only operation")
    return pin.pin_skill(name, workspace)


def skill_unpin(name: str, workspace: Path | None = None) -> Path:
    if get_current_write_origin() in _AUTONOMOUS_MUTABLE_ORIGINS:
        raise CuratorPolicyError("unpin is a foreground-only operation")
    return pin.unpin_skill(name, workspace)


def skill_write_file(
    skill_name: str,
    file_path: str,
    content: str,
    workspace: Path | None = None,
) -> Path:
    """Write a support file under <skill_dir>/{references,templates,scripts}/.

    Rejects absolute paths, ``..`` segments, anything outside the three
    allowed subdirs, and content that fails ``lint_after_write`` for its
    extension (the file is NOT written when the lint fails).
    """
    if not file_path:
        raise ValueError("file_path must not be empty")
    if Path(file_path).is_absolute() or file_path.startswith(("/", "\\")):
        raise ValueError(f"file_path must be relative: {file_path!r}")
    parts = Path(file_path).parts
    if ".." in parts:
        raise ValueError(f"file_path may not contain '..': {file_path!r}")
    if not parts or parts[0] not in _ALLOWED_FILE_SUBDIRS:
        raise ValueError(
            f"file_path must start with one of {_ALLOWED_FILE_SUBDIRS}: {file_path!r}"
        )

    skill_dir = _existing(skill_name, workspace)
    if skill_dir is None:
        raise SkillNotFoundError(f"no skill named {skill_name!r}")

    if get_current_write_origin() in _AUTONOMOUS_MUTABLE_ORIGINS:
        skill_md = skill_dir / "SKILL.md"
        parsed = parse_frontmatter(skill_md)
        if parsed is not None:
            target_fm, _ = parsed
            allowed, reason = _curator_can_modify(target_fm)
            if not allowed:
                raise CuratorPolicyError(reason)

    target = skill_dir / Path(*parts)
    from ..tools.delta_lint import lint_after_write
    lint_err = lint_after_write(target, content)
    if lint_err:
        raise ValueError(f"content failed validation: {lint_err}")

    target.parent.mkdir(parents=True, exist_ok=True)
    with snapshot_and_record(
        [skill_dir], tool_name="skill_write_file",
    ) as ctx:
        target.write_text(content, encoding="utf-8")
        ctx.record(target)
    return target


def skill_view(name: str, workspace: Path | None = None) -> str | None:
    """Return the full SKILL.md text (frontmatter + body) for ``name``."""
    skill_dir = _existing(name, workspace)
    if skill_dir is None:
        return None
    return (skill_dir / "SKILL.md").read_text(encoding="utf-8")


# -- internal helpers ----------------------------------------------------


def _validate_skill_md(serialized: str) -> None:
    """Lint the YAML frontmatter block of a SKILL.md *before* it lands.

    Catches the case where serialize_frontmatter emitted something the
    parser would later reject — should never trip in practice because
    serialize_frontmatter does its own validation, but the explicit gate
    means a partial write can never leave malformed YAML on disk.
    """
    if not serialized.startswith("---"):
        raise ValueError("SKILL.md is missing the leading frontmatter block")
    # Extract just the YAML block between the first pair of `---` lines.
    body = serialized[3:]
    end = body.find("\n---")
    if end < 0:
        raise ValueError("SKILL.md frontmatter block is not closed")
    fm_block = body[:end]
    from ..tools.delta_lint import lint_after_write
    lint_err = lint_after_write(Path("frontmatter.yaml"), fm_block)
    if lint_err:
        raise ValueError(f"SKILL.md frontmatter failed validation: {lint_err}")


def _frontmatter_to_dict(fm: SkillFrontmatter) -> dict[str, Any]:
    return {
        "name": fm.name,
        "description": fm.description,
        "version": fm.version,
        "license": fm.license,
        "compatibility": fm.compatibility,
        "metadata": dict(fm.metadata),
        "state": fm.state,
        "pinned": fm.pinned,
        "write_origin": fm.write_origin,
        "created_at": fm.created_at,
        "last_activity_at": fm.last_activity_at,
        "use_count": fm.use_count,
        "parent_session_id": fm.parent_session_id,
        "source_hermes_path": fm.source_hermes_path,
        "imported_at": fm.imported_at,
    }


def _build_frontmatter(data: dict[str, Any]) -> SkillFrontmatter:
    """Construct a SkillFrontmatter from a plain dict, dropping None entries
    so dataclass defaults take effect for unset fields."""
    cleaned = {
        k: v for k, v in data.items()
        if v is not None and k in SkillFrontmatter.__dataclass_fields__
    }
    # description has no default — supply empty string if dropped.
    cleaned.setdefault("description", data.get("description") or "")
    return SkillFrontmatter(**cleaned)
