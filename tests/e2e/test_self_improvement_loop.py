"""End-to-end tests for the three concentric self-improvement loops.

These exercise integration points (nudge → orchestrator → fork → manager,
curator → fork → YAML parse → reports → state, lifecycle runner → archive)
without a real LLM in the loop. The provider is replaced with a scripted
FakeClient or the fork itself is monkey-patched, depending on which loop
is under test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from athena.agent.fork import ForkAction, ForkResult

# ---- 1. Per-turn review -----------------------------------------------


def test_per_turn_review_creates_memory_entry_after_user_preference(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the nudge counter trips, the review orchestrator must call
    Agent.fork() with the memory + skills toolsets and the COMBINED
    addendum. We verify the call shape end-to-end (config → nudge → fork)
    without spinning up a real model."""
    from athena.config import Config
    from athena.review import nudge as nudge_mod
    from athena.review import orchestrator as orch_mod

    nudge_mod.reset_all()

    cfg = Config()
    cfg.review.nudge_interval = 3
    cfg.review.max_iterations = 4
    workspace = tmp_path / "ws"
    workspace.mkdir()
    agent = SimpleNamespace(
        cfg=cfg,
        session_id="sid-pref",
        workspace=workspace,
        last_review_summary=None,
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "from now on always check lint"},
            {"role": "assistant", "content": "got it"},
        ],
    )

    captured: list[dict[str, Any]] = []

    def fake_fork(parent, **kwargs):
        captured.append(kwargs)
        return ForkResult(
            final_response="wrote memory",
            actions=[
                ForkAction(
                    action="create",
                    target="memory",
                    name="always-check-lint",
                )
            ],
        )

    monkeypatch.setattr("athena.agent.fork.fork", fake_fork)

    # First two ticks don't fire; the third does.
    assert orch_mod.maybe_fire_review(agent) is None
    assert orch_mod.maybe_fire_review(agent) is None
    t = orch_mod.maybe_fire_review(agent)
    assert t is not None
    t.join(timeout=2)

    assert len(captured) == 1
    assert set(captured[0]["enabled_toolsets"]) == {"memory", "skills"}
    assert captured[0]["write_origin"] == "background_review"
    # The fork's actions surface on the agent for the next prompt.
    assert agent.last_review_summary["memory_writes"] == [
        {"name": "always-check-lint", "action": "create", "detail": None},
    ]


# ---- 2. Curator consolidation ------------------------------------------


def test_curator_consolidates_two_session_codename_skills_into_umbrella(
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_skill,
) -> None:
    """A curator run that returns valid YAML is committed: report files
    appear under the configured logs root and .curator_state advances."""
    from athena.config import Config, CuratorConfig
    from athena.curator import orchestrator
    from athena.curator import state as curator_state

    # Pre-create two session-codename skills under curator origin so the
    # curator's modifiability gates allow them.
    user_skills = isolated_home / ".athena" / "skills"
    user_skills.mkdir(parents=True)
    write_skill(user_skills, "foo-task-aug-12", write_origin="curator")
    write_skill(user_skills, "foo-task-aug-15", write_origin="curator")

    monkeypatch.setattr(orchestrator, "CONFIG_DIR", tmp_path)

    cfg = Config()
    cfg.curator = CuratorConfig(
        interval_hours=168,
        min_idle_hours=2,
        max_iterations=99,
    )
    store = MagicMock()
    store.most_recent_other_session.return_value = None
    agent = SimpleNamespace(
        cfg=cfg,
        session_id="curator-sid",
        session_store=store,
        workspace=tmp_path,
        client=None,
        model="qwen",
    )

    scripted_yaml = """\
Initial exploration via skills_list and skill_view…

```yaml-curator-report
runs:
  - skill: foo-task-aug-12
    decision: CONSOLIDATE_INTO
    target: foo-task-umbrella
    rationale: redundant with sibling
  - skill: foo-task-aug-15
    decision: CONSOLIDATE_INTO
    target: foo-task-umbrella
    rationale: redundant with sibling
  - skill: foo-task-umbrella
    decision: CREATE_UMBRELLA
    target: foo-task-umbrella
    rationale: new class-level skill for the foo workflow
```
"""

    def fake_fork(parent, **kwargs):
        return ForkResult(
            final_response=scripted_yaml,
            duration_s=0.1,
            child_session_id="curator-child",
        )

    monkeypatch.setattr("athena.agent.fork.fork", fake_fork)

    summary = orchestrator.maybe_run_curator(agent, force=True)
    assert summary is not None
    assert summary["decision_counts"] == {
        "CONSOLIDATE_INTO": 2,
        "CREATE_UMBRELLA": 1,
    }
    # State advanced.
    s = curator_state.read_state(tmp_path / "skills")
    assert s.last_run_at is not None
    assert s.run_count == 1
    # Reports landed on disk.
    runs = list((tmp_path / "logs" / "curator").iterdir())
    assert len(runs) == 1
    assert (runs[0] / "REPORT.md").exists()
    assert (runs[0] / "run.json").exists()


# ---- 3. Lifecycle archives stale skill ---------------------------------


def test_lifecycle_transitions_archive_unused_skill_after_90_days(
    isolated_home: Path,
    write_skill,
) -> None:
    """A background-review-origin skill last touched >90 days ago must be
    archived on the lifecycle pass."""
    user_skills = isolated_home / ".athena" / "skills"
    user_skills.mkdir(parents=True)
    long_ago = datetime.now(timezone.utc) - timedelta(days=120)
    write_skill(
        user_skills,
        "abandoned",
        write_origin="background_review",
        state="stale",
        last_activity_at=long_ago,
    )

    from athena.skills.state_machine_runner import run_lifecycle

    actions = run_lifecycle()
    assert "abandoned" in actions["archived"]
    assert not (user_skills / "abandoned").exists()
    assert (user_skills / ".archive" / "abandoned").exists()
