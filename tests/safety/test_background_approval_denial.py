"""Phase 17.7 — end-to-end background-denial test.

A background fork tries to mutate a skill via :func:`request_approval`;
the call must raise :class:`ApprovalDeniedInBackground` before any
mutation occurs, leaving the snapshot store empty and the audit log
untouched. When the same code path runs with
``auto_approve_in_background=True``, the mutation succeeds and
produces a snapshot + audit record tagged ``write_origin="background_review"``.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from athena.provenance import (
    BACKGROUND_REVIEW,
    FOREGROUND,
    reset_current_write_origin,
    set_current_write_origin,
)
from athena.safety import context as safety_context
from athena.safety.approval_guard import (
    ApprovalDeniedInBackground,
    request_approval,
    reset_approvals,
    scope_fresh_approvals,
)
from athena.safety.mutation import snapshot_and_record


@pytest.fixture(autouse=True)
def _isolate_safety():
    safety_context.reset_for_tests()
    yield
    safety_context.reset_for_tests()


async def _simulate_fork_mutation(
    skill_dir: Path,
    *,
    auto_approve: bool,
) -> bool:
    """Simulate a background-fork mutation gated by approval. Returns
    True on success, raises ApprovalDeniedInBackground on denial.

    The structure intentionally mirrors what a real Phase 3 fork
    does: scope fresh approvals, switch write_origin to
    background_review, call request_approval, and only then enter
    the snapshot+mutation block.
    """
    grants_token = scope_fresh_approvals()
    origin_token = set_current_write_origin(BACKGROUND_REVIEW)
    try:
        async def _should_never_be_called(_: str) -> bool:  # pragma: no cover
            raise AssertionError(
                "prompt callback must not run in a background fork"
            )

        approved = await request_approval(
            f"skill:{skill_dir.name}",
            _should_never_be_called,
            auto_approve_in_background=auto_approve,
        )
        if not approved:
            return False  # foreground would have refused

        # Only reached when auto_approve_in_background=True.
        with snapshot_and_record(
            [skill_dir], tool_name="background_mutation",
        ) as ctx:
            (skill_dir / "SKILL.md").write_text(
                "rewritten by background fork\n", encoding="utf-8",
            )
            ctx.record(skill_dir / "SKILL.md")
        return True
    finally:
        reset_current_write_origin(origin_token)
        reset_approvals(grants_token)


def _make_skill(isolated_home: Path) -> Path:
    skill_dir = isolated_home / ".athena" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: x\n---\n\nuser body\n",
        encoding="utf-8",
    )
    return skill_dir


# ---- background denied -----------------------------------------------


def test_background_mutation_without_auto_approve_is_denied(
    isolated_home: Path,
) -> None:
    skill_dir = _make_skill(isolated_home)
    original = (skill_dir / "SKILL.md").read_bytes()

    with pytest.raises(ApprovalDeniedInBackground):
        asyncio.run(_simulate_fork_mutation(skill_dir, auto_approve=False))

    # Skill content untouched.
    assert (skill_dir / "SKILL.md").read_bytes() == original

    # No snapshot was created — the denial happened before
    # snapshot_and_record was reached.
    store = safety_context.get_snapshot_store()
    assert store.list_snapshots() == []

    # No audit record either.
    audit_path = safety_context.get_audit_log()._current_path()
    if audit_path.exists():
        # The file may exist but must be empty (mkdir-on-init can
        # create the parent dir without writing anything).
        assert audit_path.read_text(encoding="utf-8").strip() == ""


# ---- background allowed --------------------------------------------


def test_background_mutation_with_auto_approve_proceeds(
    isolated_home: Path,
) -> None:
    skill_dir = _make_skill(isolated_home)
    result = asyncio.run(_simulate_fork_mutation(skill_dir, auto_approve=True))
    assert result is True

    # Skill rewritten.
    assert (
        skill_dir / "SKILL.md"
    ).read_text(encoding="utf-8") == "rewritten by background fork\n"

    # Snapshot recorded with write_origin=background_review.
    store = safety_context.get_snapshot_store()
    snaps = store.list_snapshots()
    assert len(snaps) == 1
    assert snaps[0].write_origin == "background_review"
    assert snaps[0].tool_name == "background_mutation"

    # Audit log carries the matching record.
    audit_path = safety_context.get_audit_log()._current_path()
    assert audit_path.exists()
    lines = [
        json.loads(line) for line in audit_path.read_text(
            encoding="utf-8"
        ).splitlines() if line
    ]
    assert any(r["write_origin"] == "background_review" for r in lines)
    assert any(r["tool_name"] == "background_mutation" for r in lines)


# ---- foreground still works ---------------------------------------


def test_foreground_mutation_still_creates_snapshot(
    isolated_home: Path,
) -> None:
    """Sanity: foreground operations are not blocked by Phase 17."""
    skill_dir = _make_skill(isolated_home)
    token = set_current_write_origin(FOREGROUND)
    try:
        with snapshot_and_record(
            [skill_dir], tool_name="foreground_mutation",
        ) as ctx:
            (skill_dir / "SKILL.md").write_text(
                "foreground edit\n", encoding="utf-8",
            )
            ctx.record(skill_dir / "SKILL.md")
    finally:
        reset_current_write_origin(token)
    store = safety_context.get_snapshot_store()
    snaps = store.list_snapshots()
    assert len(snaps) == 1
    assert snaps[0].write_origin == "foreground"
