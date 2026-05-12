"""YAML frontmatter parse/serialize for SKILL.md files.

A SKILL.md begins with a YAML frontmatter block delimited by ``---`` lines,
followed by free-form Markdown body. The frontmatter encodes both the
agentskills.io standard fields (``name``, ``description``, ``version``, …)
and ocode v2's lifecycle fields (``state``, ``pinned``, ``write_origin``,
``last_activity_at``, …).

Required fields: ``name``, ``description``. Everything else has a default.

Datetime fields are coerced to timezone-aware ``datetime`` on parse and
serialized as ISO-8601 with a ``Z`` suffix (UTC). The serializer is
deterministic — keys sort within their group (agentskills.io fields first,
then ocode v2 fields) so the output is diff-stable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


_FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)

# agentskills.io: lowercase letters, digits, hyphens; max 64 chars; not
# leading/trailing hyphen; no consecutive hyphens.
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_NAME_LEN = 64
_MAX_DESCRIPTION_LEN = 1024

# Field groupings for the serializer — keeps the on-disk YAML diff-stable
# (agentskills.io standard fields up top, ocode v2 lifecycle in the middle,
# migration-only fields at the bottom).
_AGENTSKILLS_FIELDS = (
    "name", "description", "version", "license", "compatibility", "metadata",
)
_OCODE_FIELDS = (
    "state", "pinned", "write_origin",
    "created_at", "last_activity_at", "use_count", "parent_session_id",
)
_MIGRATION_FIELDS = (
    "source_hermes_path", "imported_at",
)


class FrontmatterError(ValueError):
    """Raised when a SKILL.md frontmatter block is missing or invalid."""


@dataclass
class SkillFrontmatter:
    # agentskills.io standard
    name: str
    description: str
    version: str | None = None
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # ocode v2 lifecycle
    state: str = "active"             # active | stale | archived
    pinned: bool = False
    write_origin: str = "foreground"  # foreground | background_review | curator | migration | system
    created_at: datetime | None = None
    last_activity_at: datetime | None = None
    use_count: int = 0
    parent_session_id: str | None = None

    # Migration-only
    source_hermes_path: str | None = None
    imported_at: datetime | None = None


# -- Parsing -------------------------------------------------------------


def _coerce_datetime(value: Any) -> datetime | None:
    """Accept a datetime (naive or aware), an ISO-8601 string, or None.

    Naive datetimes are assumed UTC. ``Z`` suffix is accepted and treated as
    ``+00:00``. Empty strings and None return None. Other types raise.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    raise FrontmatterError(f"cannot coerce {value!r} to datetime")


_DATETIME_FIELDS = frozenset({"created_at", "last_activity_at", "imported_at"})
_FIELD_NAMES = frozenset(f.name for f in fields(SkillFrontmatter))


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not name:
        raise FrontmatterError("name must be a non-empty string")
    if len(name) > _MAX_NAME_LEN:
        raise FrontmatterError(f"name longer than {_MAX_NAME_LEN} chars: {name!r}")
    if not _NAME_RE.match(name):
        raise FrontmatterError(
            f"name must be lowercase alphanumeric with internal hyphens: {name!r}"
        )


def _validate_description(description: str) -> None:
    if not isinstance(description, str) or not description:
        raise FrontmatterError("description must be a non-empty string")
    if len(description) > _MAX_DESCRIPTION_LEN:
        raise FrontmatterError(
            f"description longer than {_MAX_DESCRIPTION_LEN} chars"
        )


def parse_frontmatter(path: Path) -> tuple[SkillFrontmatter, str] | None:
    """Parse a SKILL.md file. Returns ``(SkillFrontmatter, body)`` or
    raises :class:`FrontmatterError` on malformed input. Returns None only
    if the file does not exist (so callers can distinguish missing from
    malformed)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None

    m = _FM_RE.match(raw)
    if not m:
        raise FrontmatterError(f"no YAML frontmatter block in {path}")
    fm_text, body = m.group(1), m.group(2)

    try:
        data = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as e:
        raise FrontmatterError(f"invalid YAML in {path}: {e}") from e
    if not isinstance(data, dict):
        raise FrontmatterError(f"frontmatter must be a YAML mapping in {path}")

    # Required fields.
    if "name" not in data:
        raise FrontmatterError(f"missing required field 'name' in {path}")
    if "description" not in data:
        raise FrontmatterError(f"missing required field 'description' in {path}")
    _validate_name(data["name"])
    _validate_description(data["description"])

    # Drop unknown keys silently into metadata (so forward-compat fields don't
    # crash older readers); keep known fields on the dataclass.
    kwargs: dict[str, Any] = {}
    extra_metadata: dict[str, Any] = {}
    for key, value in data.items():
        if key in _FIELD_NAMES:
            if key in _DATETIME_FIELDS:
                kwargs[key] = _coerce_datetime(value)
            else:
                kwargs[key] = value
        else:
            extra_metadata[key] = value

    if extra_metadata:
        merged = dict(kwargs.get("metadata") or {})
        merged.update(extra_metadata)
        kwargs["metadata"] = merged

    return SkillFrontmatter(**kwargs), body


# -- Serialization -------------------------------------------------------


def _isoformat(dt: datetime) -> str:
    """ISO-8601 with a ``Z`` suffix when the value is UTC."""
    dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit_field(name: str, value: Any) -> tuple[str, Any] | None:
    """Filter and transform a single field for serialization."""
    if value is None:
        return None
    if name == "metadata" and not value:
        return None
    if name in _DATETIME_FIELDS:
        return name, _isoformat(value)
    return name, value


def serialize_frontmatter(fm: SkillFrontmatter, body: str) -> str:
    """Serialize a SkillFrontmatter + body back to SKILL.md text.

    Output is deterministic for diff stability: keys appear in three groups
    (agentskills.io standard, ocode v2 lifecycle, migration), sorted
    alphabetically within each group. ``None`` values are omitted entirely
    (not emitted as ``null``).
    """
    _validate_name(fm.name)
    _validate_description(fm.description)

    ordered: list[tuple[str, Any]] = []
    for group in (_AGENTSKILLS_FIELDS, _OCODE_FIELDS, _MIGRATION_FIELDS):
        rows: list[tuple[str, Any]] = []
        for key in sorted(group):
            val = getattr(fm, key)
            emitted = _emit_field(key, val)
            if emitted is not None:
                rows.append(emitted)
        ordered.extend(rows)

    # yaml.safe_dump with sort_keys=False preserves the order we built; the
    # extra ``default_flow_style=False`` keeps nested dicts in block style.
    fm_text = yaml.safe_dump(
        dict(ordered),
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    ).rstrip()

    return f"---\n{fm_text}\n---\n{body}"
