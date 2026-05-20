"""Tests for the curator+metrics wiring (T3-06R.4).

Three things land in this file:

1. ``_build_usage_section_for_prompt`` produces the section the
   curator fork sees (or returns empty string when there's nothing
   useful to surface).
2. ``_gather_usage_metrics_for_report`` populates the dict the
   reports module surfaces in REPORT.md / run.json.
3. ``athena skill metrics`` CLI command renders text + JSON.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from types import SimpleNamespace

from athena.skills.metrics import SkillMetricsStore, metrics_path


def _make_skill(workspace: Path, name: str) -> None:
    skill_dir = workspace / ".athena" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.md").write_text(
        f"---\nname: {name}\ndescription: x\nstate: active\n"
        f"pinned: false\nwrite_origin: foreground\n---\n\nbody\n",
        encoding="utf-8",
    )


def _fake_agent(profile_dir: Path, workspace: Path):
    return SimpleNamespace(
        cfg=SimpleNamespace(profile="testprofile", skill_metrics_enabled=True),
        workspace=workspace,
    )


# ---------------------------------------------------------------------------
# _build_usage_section_for_prompt
# ---------------------------------------------------------------------------


def test_never_used_appears_in_prompt_section(monkeypatch, tmp_path: Path) -> None:
    """A skill with views in the metrics file is dropped from
    'never viewed'; one without views shows up there."""
    profile = tmp_path / "profile"
    workspace = tmp_path / "ws"
    profile.mkdir()
    workspace.mkdir()
    _make_skill(workspace, "used-skill")
    _make_skill(workspace, "never-touched")

    store = SkillMetricsStore(metrics_path(profile))
    for _ in range(5):
        store.record_view("used-skill", session_id="s1")

    monkeypatch.setattr("athena.config.profile_dir", lambda _p: profile)
    monkeypatch.setattr(
        "athena.skills.discovery.discover_skills",
        lambda ws=None, **_: {
            n: (None, None) for n in ("used-skill", "never-touched")
        },
    )

    from athena.curator.orchestrator import _build_usage_section_for_prompt

    section = _build_usage_section_for_prompt(_fake_agent(profile, workspace))
    assert "Recent usage signal" in section
    assert "never-touched" in section
    # used-skill must be in Most-viewed, not Never-viewed.
    pre_never = section.split("Never viewed")[0]
    assert "used-skill" in pre_never


def test_prompt_section_empty_when_no_signal(monkeypatch, tmp_path: Path) -> None:
    """Fresh install: no metrics, no catalogue → empty section
    (the addendum keeps its baseline length)."""
    profile = tmp_path / "profile"
    workspace = tmp_path / "ws"
    profile.mkdir()
    workspace.mkdir()
    monkeypatch.setattr("athena.config.profile_dir", lambda _p: profile)
    # Empty catalogue: stub discover_skills so the user-level skills
    # dir doesn't leak in (the real ~/.athena/skills/ may have user
    # skills that wouldn't be in the test's tmp profile).
    monkeypatch.setattr(
        "athena.skills.discovery.discover_skills",
        lambda ws=None, **_: {},
    )

    from athena.curator.orchestrator import _build_usage_section_for_prompt

    assert _build_usage_section_for_prompt(_fake_agent(profile, workspace)) == ""


def test_prompt_section_skipped_when_metrics_disabled(monkeypatch, tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    workspace = tmp_path / "ws"
    profile.mkdir()
    workspace.mkdir()
    _make_skill(workspace, "alpha")
    store = SkillMetricsStore(metrics_path(profile))
    store.record_view("alpha")

    monkeypatch.setattr("athena.config.profile_dir", lambda _p: profile)
    agent = SimpleNamespace(
        cfg=SimpleNamespace(profile="testprofile", skill_metrics_enabled=False),
        workspace=workspace,
    )

    from athena.curator.orchestrator import _build_usage_section_for_prompt

    assert _build_usage_section_for_prompt(agent) == ""


# ---------------------------------------------------------------------------
# _gather_usage_metrics_for_report
# ---------------------------------------------------------------------------


def test_gather_usage_metrics_basic(monkeypatch, tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    workspace = tmp_path / "ws"
    profile.mkdir()
    workspace.mkdir()
    _make_skill(workspace, "hot")
    _make_skill(workspace, "cold")

    store = SkillMetricsStore(metrics_path(profile))
    for _ in range(8):
        store.record_view("hot", session_id="s1")
    # Inject an old view for staleness.
    old_ts = (
        (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=60))
        .isoformat()
        .replace("+00:00", "Z")
    )
    log = metrics_path(profile)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"event": "view", "skill_name": "ancient", "ts": old_ts}) + "\n")

    monkeypatch.setattr("athena.config.profile_dir", lambda _p: profile)

    from athena.curator.orchestrator import _gather_usage_metrics_for_report

    out = _gather_usage_metrics_for_report(_fake_agent(profile, workspace))
    assert out is not None
    names_top = [r["name"] for r in out["top"]]
    assert "hot" in names_top
    assert "cold" in out["never_used"]
    stale_names = [r["name"] for r in out["stale_30"]]
    assert "ancient" in stale_names


def test_gather_usage_metrics_returns_none_when_disabled(monkeypatch, tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    workspace = tmp_path / "ws"
    profile.mkdir()
    workspace.mkdir()
    monkeypatch.setattr("athena.config.profile_dir", lambda _p: profile)
    agent = SimpleNamespace(
        cfg=SimpleNamespace(profile="testprofile", skill_metrics_enabled=False),
        workspace=workspace,
    )

    from athena.curator.orchestrator import _gather_usage_metrics_for_report

    assert _gather_usage_metrics_for_report(agent) is None


# ---------------------------------------------------------------------------
# reports.write_run surfacing
# ---------------------------------------------------------------------------


def test_report_includes_usage_section(tmp_path: Path) -> None:
    """When usage_metrics is passed, REPORT.md grows a Per-skill usage
    section listing top / never / stale."""
    from athena.curator.reports import write_run

    parsed_yaml = {
        "runs": [
            {"skill": "alpha", "decision": "KEEP_AS_IS", "rationale": "ok"},
        ]
    }
    fork_result = SimpleNamespace(
        duration_s=1.0,
        error=None,
        child_session_id="cs",
        stdout="",
        stderr="",
    )
    usage = {
        "top": [
            {
                "name": "hot",
                "views": 12,
                "last_used_at": "2026-05-20T00:00:00Z",
            }
        ],
        "never_used": ["lonely"],
        "stale_30": [{"name": "ancient", "last_used_at": "2026-03-01T00:00:00Z", "views": 1}],
    }
    summary = write_run(
        agent=SimpleNamespace(),
        fork_result=fork_result,
        parsed_yaml=parsed_yaml,
        dry_run=True,
        logs_root=tmp_path,
        usage_metrics=usage,
    )
    assert "usage" in summary
    report = (Path(summary["report_path"])).read_text(encoding="utf-8")
    assert "Per-skill usage" in report
    assert "hot" in report and "12 views" in report
    assert "lonely" in report
    assert "ancient" in report


def test_report_without_usage_omits_section(tmp_path: Path) -> None:
    """``usage_metrics=None`` (the default) → no Per-skill usage
    section, so headless installs without metrics keep clean reports."""
    from athena.curator.reports import write_run

    summary = write_run(
        agent=SimpleNamespace(),
        fork_result=SimpleNamespace(
            duration_s=1.0, error=None, child_session_id="cs", stdout="", stderr=""
        ),
        parsed_yaml={"runs": []},
        dry_run=True,
        logs_root=tmp_path,
    )
    report = Path(summary["report_path"]).read_text(encoding="utf-8")
    assert "Per-skill usage" not in report


# ---------------------------------------------------------------------------
# Spec invariant — metrics inform, don't override
# ---------------------------------------------------------------------------


def test_metrics_inform_not_override(monkeypatch, tmp_path: Path) -> None:
    """T3-06R hard invariant: the curator's decisions stay in
    parsed['runs']; usage_metrics surfaces alongside them, never
    rewriting or filtering them. Even if 'alpha' is in the
    never_used list, KEEP_AS_IS lands in the report unchanged."""
    from athena.curator.reports import write_run

    parsed_yaml = {"runs": [{"skill": "alpha", "decision": "KEEP_AS_IS", "rationale": "ok"}]}
    summary = write_run(
        agent=SimpleNamespace(),
        fork_result=SimpleNamespace(
            duration_s=1.0, error=None, child_session_id="cs", stdout="", stderr=""
        ),
        parsed_yaml=parsed_yaml,
        dry_run=True,
        logs_root=tmp_path,
        usage_metrics={
            "top": [],
            "never_used": ["alpha"],
            "stale_30": [],
        },
    )
    # decisions is unchanged.
    assert summary["decisions"] == parsed_yaml["runs"]
    # The report mentions alpha both as KEEP_AS_IS AND as never-used —
    # the latter is informational, not corrective.
    report = Path(summary["report_path"]).read_text(encoding="utf-8")
    assert "KEEP_AS_IS" in report
    assert "Never viewed" in report
    assert "alpha" in report


# ---------------------------------------------------------------------------
# athena skill metrics CLI
# ---------------------------------------------------------------------------


def test_cli_skill_metrics_text(monkeypatch, tmp_path: Path, capsys) -> None:
    profile = tmp_path / "profile"
    workspace = tmp_path / "ws"
    profile.mkdir()
    workspace.mkdir()
    _make_skill(workspace, "alpha")
    _make_skill(workspace, "beta")
    store = SkillMetricsStore(metrics_path(profile))
    for _ in range(3):
        store.record_view("alpha")

    monkeypatch.setattr("athena.cli.skill.load_config", lambda: SimpleNamespace(profile="p"))
    monkeypatch.setattr("athena.config.profile_dir", lambda _p: profile)

    from athena.cli.skill import main

    rc = main(["metrics", "--top", "5", "-C", str(workspace)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "alpha" in out
    assert "beta" in out  # in never-used
    assert "3 views" in out


def test_cli_skill_metrics_json(monkeypatch, tmp_path: Path, capsys) -> None:
    profile = tmp_path / "profile"
    workspace = tmp_path / "ws"
    profile.mkdir()
    workspace.mkdir()
    _make_skill(workspace, "alpha")
    store = SkillMetricsStore(metrics_path(profile))
    store.record_view("alpha")

    monkeypatch.setattr("athena.cli.skill.load_config", lambda: SimpleNamespace(profile="p"))
    monkeypatch.setattr("athena.config.profile_dir", lambda _p: profile)

    from athena.cli.skill import main

    rc = main(["metrics", "--json", "-C", str(workspace)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {"profile", "top", "stale_days", "stale", "never_used"}
    assert any(row["name"] == "alpha" for row in payload["top"])
