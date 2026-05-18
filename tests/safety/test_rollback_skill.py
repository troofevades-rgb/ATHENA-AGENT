"""Phase 17.6 — `athena skill diff|rollback` round-trip."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.cli import skill as skill_cli
from athena.cli.rollback import diff_target, rollback_target
from athena.provenance import (
    CURATOR,
    reset_current_write_origin,
    set_current_write_origin,
)
from athena.safety import context as safety_context
from athena.skills.manager import skill_create, skill_patch


@pytest.fixture(autouse=True)
def _isolate_safety_singletons():
    safety_context.reset_for_tests()
    yield
    safety_context.reset_for_tests()


def test_skill_rollback_restores_byte_for_byte(
    isolated_home: Path,
) -> None:
    """Curator consolidates a skill; user rolls back; the SKILL.md
    bytes match the pre-consolidation state exactly."""
    token = set_current_write_origin(CURATOR)
    try:
        skill_dir = skill_create(
            "demo",
            {"description": "original", "write_origin": "curator"},
            "original body\n",
        )
        original_bytes = (skill_dir / "SKILL.md").read_bytes()

        # Simulate consolidation: rewrite the body.
        skill_patch("demo", body="consolidated body\n")
        consolidated_bytes = (skill_dir / "SKILL.md").read_bytes()
        assert consolidated_bytes != original_bytes
    finally:
        reset_current_write_origin(token)

    # Roll back to the most-recent snapshot (the one taken right
    # before the consolidating patch).
    result = rollback_target(
        skill_dir / "SKILL.md",
        tool_name="skill_rollback",
        confirm=lambda _: True,
    )
    assert result["status"] == "restored"

    # Bit-exact restore.
    restored_bytes = (skill_dir / "SKILL.md").read_bytes()
    assert restored_bytes == original_bytes


def test_skill_diff_shows_consolidation_change(
    isolated_home: Path,
) -> None:
    token = set_current_write_origin(CURATOR)
    try:
        skill_dir = skill_create(
            "demo",
            {"description": "original", "write_origin": "curator"},
            "original body\n",
        )
        skill_patch("demo", body="consolidated body\n")
    finally:
        reset_current_write_origin(token)

    diff = diff_target(skill_dir / "SKILL.md")
    assert "original body" in diff
    assert "consolidated body" in diff


def test_audit_log_records_both_consolidate_and_rollback(
    isolated_home: Path,
) -> None:
    """After consolidate + rollback the audit log contains both
    operations, in order, with snapshot ids linking each step."""
    token = set_current_write_origin(CURATOR)
    try:
        skill_dir = skill_create(
            "demo",
            {"description": "x", "write_origin": "curator"},
            "before\n",
        )
        skill_patch("demo", body="after\n")
    finally:
        reset_current_write_origin(token)

    rollback_target(
        skill_dir / "SKILL.md",
        tool_name="skill_rollback",
        confirm=lambda _: True,
    )

    audit_log = safety_context.get_audit_log()
    log_path = audit_log._current_path()
    assert log_path.exists()
    lines = [
        json.loads(line) for line in log_path.read_text(
            encoding="utf-8"
        ).splitlines() if line
    ]
    tool_names = [r["tool_name"] for r in lines]
    assert "skill_create" in tool_names
    assert "skill_patch" in tool_names
    assert "skill_rollback" in tool_names
    # The rollback record's sha_after must match the pre-consolidate
    # state's sha (i.e., the skill_create record's sha_after).
    create_after = next(
        r for r in lines if r["tool_name"] == "skill_create"
    )["sha_after"]
    rollback_after = next(
        r for r in lines if r["tool_name"] == "skill_rollback"
    )["sha_after"]
    assert create_after == rollback_after


def test_skill_cli_diff_after_patch_shows_change(
    isolated_home: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    token = set_current_write_origin(CURATOR)
    try:
        skill_create(
            "demo",
            {"description": "x", "write_origin": "curator"},
            "old body\n",
        )
        skill_patch("demo", body="new body\n")
    finally:
        reset_current_write_origin(token)
    rc = skill_cli.main(["diff", "demo"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "old body" in captured.out
    assert "new body" in captured.out


def test_skill_cli_rollback_with_yes_flag(
    isolated_home: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    token = set_current_write_origin(CURATOR)
    try:
        skill_dir = skill_create(
            "demo",
            {"description": "x", "write_origin": "curator"},
            "pre\n",
        )
        skill_patch("demo", body="post\n")
    finally:
        reset_current_write_origin(token)
    rc = skill_cli.main(["rollback", "demo", "-y"])
    assert rc == 0
    assert "pre" in (skill_dir / "SKILL.md").read_text(encoding="utf-8")


def test_skill_cli_unknown_name_returns_error(
    isolated_home: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = skill_cli.main(["diff", "ghost"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "no skill" in captured.err.lower()
