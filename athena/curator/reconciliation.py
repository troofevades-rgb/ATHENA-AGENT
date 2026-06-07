"""Filesystem reconciliation for curator runs.

Snapshots the skill landscape before the curator fork runs, then diffs
against post-fork state. The drift report flags three failure modes:

- ``missing_from_fs``: the curator claimed it archived/consolidated a
  skill but the filesystem still shows it active.
- ``unexpected_archive``: a skill was archived on disk that the curator
  did not name in its YAML output. (Could be a sibling cleanup the
  curator forgot to record; could also be a side-effect bug.)
- ``no_op_after_keep``: claimed KEEP_AS_IS but ``state`` flipped — the
  curator either changed its mind mid-run or the skill was touched by
  another writer between snapshot and reconcile.

Hermes Agent's equivalent lives in ``agent/curator.py`` as
``_classify_removed_skills`` + ``_reconcile_classification``. Drift
goes into ``run.json`` so the next ``athena curator inspect-last``
surfaces it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..skills.discovery import discover_skills

# Decisions that should cause the skill to NOT be present as active
# anymore. Curator may either archive (CONSOLIDATE_INTO, DEMOTE_TO_*,
# PRUNE) or replace-with-umbrella (CREATE_UMBRELLA — the new umbrella
# IS the row, others get absorbed in separate rows).
_REMOVAL_DECISIONS = frozenset(
    {
        "CONSOLIDATE_INTO",
        "DEMOTE_TO_REFERENCES",
        "DEMOTE_TO_TEMPLATES",
        "DEMOTE_TO_SCRIPTS",
        "PRUNE",
    }
)

# Decisions that should NOT change the skill's state.
_NO_OP_DECISIONS = frozenset({"KEEP_AS_IS"})


@dataclass
class SkillSnapshot:
    """A point-in-time read of one skill's filesystem state."""

    name: str
    state: str  # "active" | "stale" | "archived" — frontmatter
    is_archived: bool  # True if the directory lives under .archive/
    skill_dir: str  # absolute path string


@dataclass
class DriftReport:
    """Per-run drift summary attached to the run.json record."""

    missing_from_fs: list[dict[str, str]] = field(default_factory=list)
    unexpected_archive: list[dict[str, str]] = field(default_factory=list)
    no_op_after_keep: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        return {
            "missing_from_fs": list(self.missing_from_fs),
            "unexpected_archive": list(self.unexpected_archive),
            "no_op_after_keep": list(self.no_op_after_keep),
        }

    @property
    def is_clean(self) -> bool:
        return not (self.missing_from_fs or self.unexpected_archive or self.no_op_after_keep)


def snapshot_skills(workspace: Path | None = None) -> dict[str, SkillSnapshot]:
    """Read the full skill catalog (active + archived) into snapshots.

    Returns a name → :class:`SkillSnapshot` map. Used as the *before*
    half of a reconciliation pair. Order doesn't matter; identity is
    by name.
    """
    snapshots: dict[str, SkillSnapshot] = {}
    for name, (fm, skill_dir) in discover_skills(workspace, include_archived=True).items():
        snapshots[name] = SkillSnapshot(
            name=name,
            state=fm.state or "active",
            is_archived=fm.state == "archived" or ".archive" in str(skill_dir),
            skill_dir=str(skill_dir),
        )
    return snapshots


def reconcile(
    before: dict[str, SkillSnapshot],
    after: dict[str, SkillSnapshot],
    yaml_runs: list[dict[str, Any]],
) -> DriftReport:
    """Diff before/after, classify against the curator's stated plan.

    ``yaml_runs`` is the parsed list under the YAML report's ``runs``
    key — each entry has ``skill``, ``decision``, ``target``,
    ``absorbed_into``, ``rationale``.

    Drift classification:

    - For every ``skill`` the YAML marked as a removal decision, expect
      ``after[skill].is_archived`` (or absent). Otherwise → drift.
    - For every name present in ``before`` but archived in ``after``,
      the YAML must mention it as a removal decision. Otherwise → drift.
    - For every YAML KEEP_AS_IS row, compare states; flipped → drift.

    Returns a :class:`DriftReport`. Caller decides whether to act on
    drift (log warning, surface in REPORT.md, fail the run, etc.).
    """
    report = DriftReport()

    claimed_removals = {
        r["skill"]: r["decision"] for r in yaml_runs if r.get("decision") in _REMOVAL_DECISIONS
    }
    claimed_keeps = {
        r["skill"]: r["decision"] for r in yaml_runs if r.get("decision") in _NO_OP_DECISIONS
    }

    # 1. Claimed removals that didn't actually happen.
    for skill, decision in claimed_removals.items():
        post = after.get(skill)
        if post is None:
            # Removed entirely from disk — only acceptable when
            # something deleted the dir wholesale, which our archive
            # path doesn't do. Treat as clean for now (defensive).
            continue
        if not post.is_archived:
            report.missing_from_fs.append(
                {
                    "skill": skill,
                    "decision": decision,
                    "observed_state": post.state,
                }
            )

    # 2. Disk archived skills the YAML did NOT name.
    yaml_named = {r["skill"] for r in yaml_runs}
    for skill, pre in before.items():
        post = after.get(skill)
        if post is None or pre.is_archived or not post.is_archived:
            continue
        if skill in yaml_named:
            # If the YAML named it, the claim above already covered it.
            continue
        report.unexpected_archive.append(
            {
                "skill": skill,
                "before_state": pre.state,
                "after_state": post.state,
            }
        )

    # 3. KEEP_AS_IS that flipped state.
    for skill in claimed_keeps:
        kept_pre = before.get(skill)
        kept_post = after.get(skill)
        if kept_pre is None or kept_post is None:
            continue
        if kept_pre.state != kept_post.state or kept_pre.is_archived != kept_post.is_archived:
            report.no_op_after_keep.append(
                {
                    "skill": skill,
                    "before_state": kept_pre.state,
                    "after_state": kept_post.state,
                }
            )

    return report
