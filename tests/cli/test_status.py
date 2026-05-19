"""``athena status`` — read the live snapshot for the active profile."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.cli import status as cli


@pytest.fixture(autouse=True)
def isolated_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Point profile_dir resolution at tmp_path so .status.json
    reads/writes can't escape into the real ~/.athena."""
    from athena import config as cfg_mod
    from athena.profiles import resolution

    def fake_profile_dir(name="default", home=None):
        path = tmp_path / "athena_home" / "profiles" / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(cfg_mod, "profile_dir", fake_profile_dir)
    monkeypatch.setattr(cli, "profile_dir", fake_profile_dir)
    monkeypatch.setattr(resolution, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(
        resolution,
        "ACTIVE_PROFILE_FILE",
        tmp_path / "active_profile",
    )
    monkeypatch.delenv("ATHENA_PROFILE", raising=False)
    monkeypatch.delenv("OCODE_PROFILE", raising=False)
    # Stable load_config — Config defaults are fine for these tests.
    from athena.config import Config

    monkeypatch.setattr(cli, "load_config", lambda: Config(profile="default"))
    return tmp_path


def _write_snapshot(profile_root: Path, profile: str, payload: dict) -> Path:
    target = profile_root / "athena_home" / "profiles" / profile
    target.mkdir(parents=True, exist_ok=True)
    snapshot = target / ".status.json"
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    return snapshot


# ---- no snapshot present -----------------------------------------


def test_no_snapshot_human_message(
    isolated_home: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no live athena process" in out
    assert "default" in out


def test_no_snapshot_json_returns_inactive(
    isolated_home: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"active": False, "profile": "default"}


# ---- happy path ----------------------------------------------------


def test_renders_snapshot(
    isolated_home: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write_snapshot(
        isolated_home,
        "default",
        {
            "profile": "default",
            "session_id": "abc-123",
            "model": "qwen2.5-coder:14b",
            "provider": "ollama",
            "elapsed_seconds": 42.5,
            "turns": 3,
            "tool_calls": 7,
            "tool_call_counts": {"Read": 4, "Bash": 3},
            "prompt_tokens": 1500,
            "completion_tokens": 2000,
            "total_tokens": 3500,
            "fork_count": 1,
            "review_fired_count": 0,
            "curator_run_count": 0,
        },
    )
    rc = cli.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "abc-123" in out
    assert "qwen2.5-coder:14b" in out
    assert "ollama" in out
    assert "Read" in out and "4" in out
    assert "Bash" in out and "3" in out
    assert "1500" in out
    assert "3500" in out


def test_json_output_is_raw_snapshot(
    isolated_home: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    payload = {
        "profile": "default",
        "session_id": "s",
        "model": "m",
        "provider": "p",
        "turns": 1,
    }
    _write_snapshot(isolated_home, "default", payload)
    rc = cli.main(["--json"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed == payload


# ---- profile resolution -------------------------------------------


def test_explicit_profile_flag(
    isolated_home: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write_snapshot(
        isolated_home,
        "work",
        {
            "profile": "work",
            "session_id": "w-1",
            "model": "m",
            "provider": "p",
            "turns": 5,
        },
    )
    rc = cli.main(["--profile", "work"])
    out = capsys.readouterr().out
    assert "work" in out
    assert "w-1" in out


def test_profile_from_env_var(
    isolated_home: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_snapshot(
        isolated_home,
        "work",
        {
            "profile": "work",
            "session_id": "envwins",
            "model": "m",
            "provider": "p",
        },
    )
    monkeypatch.setenv("ATHENA_PROFILE", "work")
    rc = cli.main([])
    assert "envwins" in capsys.readouterr().out


# ---- malformed snapshot -------------------------------------------


def test_malformed_json_returns_1(
    isolated_home: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    snapshot = isolated_home / "athena_home" / "profiles" / "default" / ".status.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("not json", encoding="utf-8")
    rc = cli.main([])
    assert rc == 1
    assert "failed to read" in capsys.readouterr().err


# ---- render_status ------------------------------------------------


def test_render_status_includes_every_field() -> None:
    out = cli.render_status(
        {
            "profile": "p",
            "session_id": "s",
            "model": "m",
            "provider": "v",
            "elapsed_seconds": 90.0,
            "turns": 2,
            "tool_calls": 5,
            "tool_call_counts": {"Bash": 3, "Read": 2},
            "prompt_tokens": 100,
            "completion_tokens": 200,
            "total_tokens": 300,
            "fork_count": 1,
            "review_fired_count": 1,
            "curator_run_count": 0,
        }
    )
    for needle in (
        "p",
        "s",
        "m",
        "v",
        "100",
        "200",
        "300",
        "turns",
        "tool calls",
        "forks",
        "reviews",
        "tool histogram",
        "Bash",
        "Read",
    ):
        assert needle in out


def test_render_status_missing_session_shows_na() -> None:
    out = cli.render_status(
        {
            "profile": "default",
            "session_id": None,
            "model": "m",
            "provider": "p",
        }
    )
    assert "n/a" in out


def test_render_status_empty_histogram_section_omitted() -> None:
    out = cli.render_status(
        {
            "profile": "p",
            "session_id": "s",
            "model": "m",
            "provider": "v",
            "tool_call_counts": {},
        }
    )
    assert "tool histogram" not in out


def test_render_status_histogram_sorted_by_count_desc() -> None:
    out = cli.render_status(
        {
            "profile": "p",
            "session_id": "s",
            "model": "m",
            "provider": "v",
            "tool_call_counts": {"Rare": 1, "Common": 50, "Mid": 10},
        }
    )
    # "Common" should appear before "Mid" before "Rare".
    common_pos = out.index("Common")
    mid_pos = out.index("Mid")
    rare_pos = out.index("Rare")
    assert common_pos < mid_pos < rare_pos


def test_human_duration_seconds() -> None:
    assert cli._human_duration(5.4) == "5.4s"
    assert cli._human_duration(45.0) == "45.0s"


def test_human_duration_minutes() -> None:
    assert cli._human_duration(90.0) == "1m30s"


def test_human_duration_hours() -> None:
    assert cli._human_duration(3661.0) == "1h01m"


# ---- /status renderer parity --------------------------------------


def test_status_snapshot_to_render_round_trip() -> None:
    """Stats.to_snapshot output must be consumable by render_status
    without massaging — locks the contract between the two surfaces."""
    from athena.agent.core import Stats

    stats = Stats()
    stats.record_tool_call("Read")
    stats.record_tool_call("Bash")
    stats.record_tool_call("Bash")
    stats.turns = 1
    stats.prompt_tokens = 100
    stats.eval_tokens = 200
    snapshot = stats.to_snapshot(
        session_id="sess",
        model="qwen",
        provider="ollama",
        profile="work",
    )
    rendered = cli.render_status(snapshot)
    assert "qwen" in rendered
    assert "work" in rendered
    assert "Bash" in rendered and "2" in rendered  # 2 Bash calls
    assert "Read" in rendered and "1" in rendered
    assert "300" in rendered  # total tokens
