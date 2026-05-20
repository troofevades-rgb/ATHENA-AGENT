"""On-demand loader for SKILL.md bodies and reference files.

Discovery only scans frontmatter (cheap). The full body is loaded lazily —
either when the model invokes ``skill_view`` or pulls from the reference
attachments. A per-process cache avoids re-reading the same file repeatedly
within a session; ``invalidate(name, workspace)`` is called by the skill
manager when a body is rewritten.
"""

from __future__ import annotations

from pathlib import Path

from .discovery import discover_skills
from .frontmatter import parse_frontmatter

# Cache key is (workspace_path_str_or_empty, skill_name) so a workspace
# override and a user skill of the same name don't collide.
_BODY_CACHE: dict[tuple[str, str], str] = {}


def _key(name: str, workspace: Path | None) -> tuple[str, str]:
    return (str(workspace) if workspace else "", name)


def _resolve(name: str, workspace: Path | None) -> Path | None:
    skills = discover_skills(workspace, include_archived=True)
    entry = skills.get(name)
    return entry[1] if entry else None


def load_body(name: str, workspace: Path | None = None) -> str | None:
    """Return the body text of ``name``'s SKILL.md, or None if not found.

    Cached per (workspace, name) until ``invalidate`` is called.
    """
    key = _key(name, workspace)
    cached = _BODY_CACHE.get(key)
    if cached is not None:
        # Repeat reads count as fresh disclosures — the model still
        # paid attention to the skill on this turn even if our cache
        # spared the disk read.
        _record_view(name)
        return cached
    skill_dir = _resolve(name, workspace)
    if skill_dir is None:
        return None
    parsed = parse_frontmatter(skill_dir / "SKILL.md")
    if parsed is None:
        return None
    _fm, body = parsed
    _BODY_CACHE[key] = body
    _record_view(name)
    return body


def _record_view(name: str) -> None:
    """Notify the active T3-06R SkillMetricsStore (if any) that this
    skill body was disclosed. Lazy import dodges a skills →
    skills.metrics import cycle in test fixtures that build a stub
    Agent before the metrics module is touched."""
    try:
        from .metrics import record_view_active

        record_view_active(name)
    except Exception:  # noqa: BLE001
        # Metrics recording is best-effort. A bug there must never
        # block a skill load.
        pass


def invalidate(name: str, workspace: Path | None = None) -> None:
    """Drop ``name``'s cached body. Called by the skill manager on mutations."""
    _BODY_CACHE.pop(_key(name, workspace), None)


def invalidate_all() -> None:
    """Drop the entire cache. Used by tests and by ``/clear``-style resets."""
    _BODY_CACHE.clear()


_ALLOWED_SUBDIRS = ("references", "templates", "scripts")


def load_reference(
    name: str,
    ref_path: str,
    workspace: Path | None = None,
) -> str | None:
    """Read ``<skill_dir>/<ref_path>`` for one of the allowed subdirs.

    Rejects absolute paths and any path containing ``..`` segments. Returns
    None when the skill or the file doesn't exist.
    """
    if not ref_path:
        return None
    # Catch both posix-absolute ("/x") and windows-absolute ("C:\x", "\x")
    # since pathlib's is_absolute() is platform-specific.
    if Path(ref_path).is_absolute() or ref_path.startswith(("/", "\\")):
        raise ValueError(f"reference path must be relative: {ref_path!r}")
    parts = Path(ref_path).parts
    if ".." in parts:
        raise ValueError(f"reference path may not contain '..': {ref_path!r}")
    if not parts or parts[0] not in _ALLOWED_SUBDIRS:
        raise ValueError(f"reference path must start with one of {_ALLOWED_SUBDIRS}: {ref_path!r}")

    skill_dir = _resolve(name, workspace)
    if skill_dir is None:
        return None
    target = skill_dir / Path(*parts)
    if not target.exists() or not target.is_file():
        return None
    return target.read_text(encoding="utf-8")
