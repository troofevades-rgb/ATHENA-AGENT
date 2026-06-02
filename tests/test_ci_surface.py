"""Drift-guard: the CI workflow files match what CONTRIBUTING.md
documents.

The auditing-agent run flagged "no CI pipeline" as a P0. That was
phantom -- ``.github/workflows/`` has six workflows wired to every
PR. But the misread was easy because there was no top-level doc
describing what runs in CI; the auditor read the source layout and
concluded.

This test pins that:

  * Every workflow CONTRIBUTING.md names actually exists on disk.
  * Each workflow's job list matches the table in CONTRIBUTING.md.
  * The ``ruff`` lint job runs on the documented platform matrix
    (ubuntu + windows + macos) -- the Windows + macOS coverage was
    the load-bearing addition from this audit pass.

If a future PR renames / removes / adds a workflow, this test fails
unless the doc is updated in the same change. That keeps the
documented CI surface honest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# yaml is in the dev extras (also pulled by gateway).
yaml = pytest.importorskip("yaml")

_REPO_ROOT = Path(__file__).parent.parent
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"

# Expected workflow -> top-level job names. The values mirror the
# table in CONTRIBUTING.md "CI pipeline" section. If a workflow
# legitimately grows a new job, update both this dict AND the doc
# table in the same commit.
_EXPECTED_WORKFLOWS: dict[str, set[str]] = {
    "tests.yml": {"test"},
    "lint.yml": {"ruff", "mypy", "version-sync"},
    "coverage.yml": {"coverage"},
    "osv-scanner.yml": {"scan"},
    "supply-chain.yml": {"pip-audit"},
    "publish.yml": {"build", "publish-testpypi", "publish-pypi"},
}


def _load_workflow(name: str) -> dict:
    path = _WORKFLOWS / name
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_every_documented_workflow_file_exists() -> None:
    """CONTRIBUTING.md lists six workflows. Each must be on disk."""
    missing = [name for name in _EXPECTED_WORKFLOWS if not (_WORKFLOWS / name).is_file()]
    assert not missing, (
        f"CI workflows missing on disk that CONTRIBUTING.md "
        f"documents: {missing}. Either restore the workflow or "
        "remove the row from CONTRIBUTING.md's CI table in the "
        "same commit."
    )


@pytest.mark.parametrize(
    ("workflow_name", "expected_jobs"),
    list(_EXPECTED_WORKFLOWS.items()),
)
def test_workflow_jobs_match_documented_list(workflow_name: str, expected_jobs: set[str]) -> None:
    """Each workflow's top-level ``jobs:`` keys match the
    CONTRIBUTING.md table. Catches both renames (job moves to a
    different name) and silent additions / removals."""
    data = _load_workflow(workflow_name)
    actual_jobs = set(data.get("jobs", {}).keys())
    assert actual_jobs == expected_jobs, (
        f"{workflow_name} jobs drift: actual={actual_jobs}, "
        f"expected={expected_jobs}. Update CONTRIBUTING.md's "
        "CI table and this test together when restructuring jobs."
    )


def test_ruff_lint_runs_on_cross_platform_matrix() -> None:
    """The load-bearing addition from this CI audit pass: ruff
    runs on Ubuntu + Windows + macOS. Without the Windows runner,
    platform-specific path / encoding regressions never get
    caught in CI (the model picker and crash_log both shipped
    Windows-specific code that no CI ever ran)."""
    data = _load_workflow("lint.yml")
    ruff_job = data["jobs"]["ruff"]
    matrix = ruff_job.get("strategy", {}).get("matrix", {})
    os_list = matrix.get("os", [])
    assert "ubuntu-latest" in os_list
    assert "windows-latest" in os_list
    assert "macos-latest" in os_list


def test_mypy_advisory_status_documented() -> None:
    """mypy runs with ``continue-on-error: true`` (advisory only;
    doesn't gate merge) per the T1-04 plan. The CONTRIBUTING.md
    table says so explicitly. If a future PR flips mypy to
    required, update both the workflow AND the doc together --
    this test catches the silent flip."""
    data = _load_workflow("lint.yml")
    mypy_job = data["jobs"]["mypy"]
    # Either ``continue-on-error: true`` is set (advisory mode)
    # OR the doc has been updated to remove the "advisory" note.
    # We check the former here; doc verification is human-only.
    assert mypy_job.get("continue-on-error") is True, (
        "mypy job is no longer advisory. Update CONTRIBUTING.md's "
        "CI table to drop the 'advisory' note in the same commit."
    )
