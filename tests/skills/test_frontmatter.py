"""Tests for SKILL.md YAML frontmatter parse/serialize."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ocode.skills.frontmatter import (
    FrontmatterError,
    SkillFrontmatter,
    parse_frontmatter,
    serialize_frontmatter,
)


def _write(tmp_path: Path, body: str, name: str = "SKILL.md") -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_parse_minimal_frontmatter(tmp_path: Path) -> None:
    p = _write(tmp_path, "---\nname: my-skill\ndescription: A skill.\n---\nbody text\n")
    fm, body = parse_frontmatter(p)
    assert fm.name == "my-skill"
    assert fm.description == "A skill."
    assert fm.state == "active"
    assert fm.pinned is False
    assert fm.write_origin == "foreground"
    assert fm.created_at is None
    assert body == "body text\n"


def test_parse_full_frontmatter(tmp_path: Path) -> None:
    p = _write(tmp_path, """---
name: full-skill
description: A full skill.
version: "1.2.3"
license: MIT
compatibility: ocode>=0.2
metadata:
  category: workflow
state: stale
pinned: true
write_origin: curator
created_at: 2026-01-15T10:00:00Z
last_activity_at: 2026-04-20T15:30:00Z
use_count: 7
parent_session_id: sess-abc
source_hermes_path: /home/me/.hermes/skills/full-skill
imported_at: 2026-05-01T00:00:00Z
---
body
""")
    fm, body = parse_frontmatter(p)
    assert fm.name == "full-skill"
    assert fm.version == "1.2.3"
    assert fm.license == "MIT"
    assert fm.compatibility == "ocode>=0.2"
    assert fm.metadata == {"category": "workflow"}
    assert fm.state == "stale"
    assert fm.pinned is True
    assert fm.write_origin == "curator"
    assert fm.created_at == datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    assert fm.last_activity_at == datetime(2026, 4, 20, 15, 30, tzinfo=timezone.utc)
    assert fm.use_count == 7
    assert fm.parent_session_id == "sess-abc"
    assert fm.source_hermes_path == "/home/me/.hermes/skills/full-skill"
    assert fm.imported_at == datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    assert body == "body\n"


def test_parse_rejects_missing_required_fields(tmp_path: Path) -> None:
    p = _write(tmp_path, "---\ndescription: missing name\n---\n")
    with pytest.raises(FrontmatterError, match="missing required field 'name'"):
        parse_frontmatter(p)

    p = _write(tmp_path, "---\nname: no-desc\n---\n", name="b.md")
    with pytest.raises(FrontmatterError, match="missing required field 'description'"):
        parse_frontmatter(p)


def test_parse_rejects_invalid_name(tmp_path: Path) -> None:
    p = _write(tmp_path, "---\nname: Has-Caps\ndescription: x\n---\n")
    with pytest.raises(FrontmatterError, match="lowercase alphanumeric"):
        parse_frontmatter(p)

    p2 = _write(tmp_path, "---\nname: -leading\ndescription: x\n---\n", name="b.md")
    with pytest.raises(FrontmatterError):
        parse_frontmatter(p2)


def test_parse_rejects_oversize_description(tmp_path: Path) -> None:
    desc = "x" * 1025
    p = _write(tmp_path, f"---\nname: ok\ndescription: {desc}\n---\n")
    with pytest.raises(FrontmatterError, match="description longer than"):
        parse_frontmatter(p)


def test_parse_missing_file_returns_none(tmp_path: Path) -> None:
    assert parse_frontmatter(tmp_path / "nope.md") is None


def test_parse_rejects_no_frontmatter_block(tmp_path: Path) -> None:
    p = _write(tmp_path, "just a body, no YAML")
    with pytest.raises(FrontmatterError, match="no YAML frontmatter"):
        parse_frontmatter(p)


def test_unknown_fields_fold_into_metadata(tmp_path: Path) -> None:
    p = _write(tmp_path, """---
name: forward-compat
description: x
new_future_field: "future"
metadata:
  existing: value
---
""")
    fm, _ = parse_frontmatter(p)
    assert fm.metadata == {"existing": "value", "new_future_field": "future"}


def test_serialize_round_trips(tmp_path: Path) -> None:
    fm = SkillFrontmatter(
        name="round-trip",
        description="A skill.",
        version="0.1",
        state="stale",
        pinned=True,
        created_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    )
    text = serialize_frontmatter(fm, "body line\nsecond\n")
    p = tmp_path / "SKILL.md"
    p.write_text(text, encoding="utf-8")
    fm2, body = parse_frontmatter(p)
    assert fm2.name == fm.name
    assert fm2.description == fm.description
    assert fm2.version == fm.version
    assert fm2.state == fm.state
    assert fm2.pinned is True
    assert fm2.created_at == fm.created_at
    assert body == "body line\nsecond\n"


def test_serialize_is_deterministic_sorted_keys() -> None:
    fm = SkillFrontmatter(
        name="det",
        description="x",
        version="1",
        license="MIT",
        state="active",
        pinned=False,
        write_origin="foreground",
    )
    out1 = serialize_frontmatter(fm, "body")
    out2 = serialize_frontmatter(fm, "body")
    assert out1 == out2

    # agentskills.io group appears before ocode v2 group; within each, sorted.
    yaml_block = out1.split("---\n")[1]
    lines = [ln.split(":")[0] for ln in yaml_block.splitlines() if ln and not ln.startswith(" ")]
    # description < license < name < version alphabetically (agentskills group)
    # then pinned < state < write_origin (ocode group)
    assert lines.index("description") < lines.index("pinned")
    assert lines.index("name") < lines.index("state")
    # Inside groups, sorted alpha:
    asg = [ln for ln in lines if ln in {"description", "license", "name", "version"}]
    assert asg == sorted(asg)
    osg = [ln for ln in lines if ln in {"pinned", "state", "write_origin"}]
    assert osg == sorted(osg)


def test_serialize_omits_none_values() -> None:
    fm = SkillFrontmatter(name="omit", description="x")
    out = serialize_frontmatter(fm, "")
    assert "version" not in out
    assert "license" not in out
    assert "created_at" not in out
    assert "null" not in out


def test_datetime_coercion(tmp_path: Path) -> None:
    """Both naive ISO strings and Z-suffixed strings parse to UTC-aware."""
    p = _write(tmp_path, """---
name: dt
description: x
created_at: 2026-01-01T00:00:00
last_activity_at: 2026-02-02T03:04:05Z
---
""")
    fm, _ = parse_frontmatter(p)
    assert fm.created_at == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert fm.last_activity_at == datetime(2026, 2, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_datetime_serialization_uses_z_suffix() -> None:
    fm = SkillFrontmatter(
        name="dt",
        description="x",
        created_at=datetime(2026, 7, 4, 12, 30, tzinfo=timezone.utc),
    )
    out = serialize_frontmatter(fm, "")
    # The Z-suffix is what matters; yaml may emit quotes around the timestamp.
    assert "2026-07-04T12:30:00Z" in out
