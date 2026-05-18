"""``athena profile`` CLI subcommands."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.cli import profile as cli
from athena.profiles import manager, resolution


@pytest.fixture(autouse=True)
def isolated_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    home = tmp_path / "athena_home"
    home.mkdir()
    monkeypatch.setattr(resolution, "PROFILES_DIR", home / "profiles")
    monkeypatch.setattr(
        resolution, "ACTIVE_PROFILE_FILE", home / "active_profile",
    )
    monkeypatch.setattr(manager, "PROFILES_DIR", home / "profiles")
    monkeypatch.setattr(
        manager, "ACTIVE_PROFILE_FILE", home / "active_profile",
    )
    # CLI imports the symbols from the resolution module — patch
    # those references too so the CLI sees the test paths.
    monkeypatch.setattr(cli, "ACTIVE_PROFILE_FILE", home / "active_profile")
    monkeypatch.setattr(cli, "profile_dir", resolution.profile_dir)
    monkeypatch.setattr(cli, "profile_exists", resolution.profile_exists)
    monkeypatch.setattr(
        cli, "resolve_active_profile", resolution.resolve_active_profile,
    )
    monkeypatch.delenv("ATHENA_PROFILE", raising=False)
    monkeypatch.delenv("OCODE_PROFILE", raising=False)
    return home


# ---- list -----------------------------------------------------------


def test_list_empty(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["list"])
    assert rc == 0
    assert "no profiles configured" in capsys.readouterr().out


def test_list_marks_active(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("default")
    manager.create_profile("work")
    manager.switch_profile("work")
    rc = cli.main(["list"])
    out = capsys.readouterr().out
    # work is active → marked with *.
    lines = [l for l in out.splitlines() if l.strip()]
    assert any(l.startswith("* work") for l in lines)
    assert any(l.startswith("  default") for l in lines)


def test_list_json_output(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("default")
    manager.create_profile("work")
    cli.main(["list", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["profiles"] == ["default", "work"]
    assert payload["active"] == "default"


# ---- show -----------------------------------------------------------


def test_show_active_profile(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("default")
    manager.create_profile("work")
    manager.switch_profile("work")
    rc = cli.main(["show"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "work" in out
    assert "path:" in out
    assert "skills:" in out


def test_show_named_profile(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("client-acme")
    rc = cli.main(["show", "client-acme"])
    out = capsys.readouterr().out
    assert "client-acme" in out


def test_show_unknown_returns_2(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["show", "ghost"])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_show_invalid_name_returns_2(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["show", "Bad Name"])
    assert rc == 2


def test_show_json_carries_counts_and_path(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("work")
    # Populate a few items so the counts are nonzero.
    work = resolution.profile_dir("work")
    (work / "skills" / "skill-a").mkdir()
    (work / "memory" / "note.md").write_text("hi", encoding="utf-8")
    (work / "goal.txt").write_text("write idiomatic Rust", encoding="utf-8")
    cli.main(["show", "work", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "work"
    assert payload["skills_count"] == 1
    assert payload["memory_count"] == 1
    assert payload["has_config_toml"] is True
    assert payload["goal"] == "write idiomatic Rust"


# ---- create ---------------------------------------------------------


def test_create_succeeds(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["create", "work"])
    assert rc == 0
    assert "created profile 'work'" in capsys.readouterr().out
    assert resolution.profile_exists("work")


def test_create_with_copy_from(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("source")
    (resolution.profile_dir("source") / "skills" / "shared").mkdir()
    rc = cli.main(["create", "target", "--copy-from", "source"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "cloned from: source" in out
    assert (resolution.profile_dir("target") / "skills" / "shared").exists()


def test_create_invalid_name_returns_2(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["create", "Bad Name"])
    assert rc == 2
    assert "invalid" in capsys.readouterr().err


def test_create_duplicate_returns_2(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("work")
    rc = cli.main(["create", "work"])
    assert rc == 2
    assert "already exists" in capsys.readouterr().err


def test_create_copy_from_missing_returns_2(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["create", "target", "--copy-from", "ghost"])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


# ---- switch ---------------------------------------------------------


def test_switch_writes_active(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("work")
    rc = cli.main(["switch", "work"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "work" in out
    assert resolution.ACTIVE_PROFILE_FILE.read_text() == "work"


def test_switch_missing_returns_2(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["switch", "ghost"])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


# ---- delete ---------------------------------------------------------


def test_delete_with_matching_token(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("work")
    rc = cli.main(["delete", "work", "work"])
    assert rc == 0
    assert not resolution.profile_exists("work")


def test_delete_with_mismatched_token_returns_2(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("work")
    rc = cli.main(["delete", "work", "wrong-token"])
    assert rc == 2
    assert resolution.profile_exists("work")  # still there
    assert "must equal" in capsys.readouterr().err


def test_delete_default_protected(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("default")
    rc = cli.main(["delete", "default", "default"])
    assert rc == 2
    assert resolution.profile_exists("default")


# ---- rename ---------------------------------------------------------


def test_rename_moves_profile(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("old")
    rc = cli.main(["rename", "old", "new"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "old" in out and "new" in out
    assert not resolution.profile_exists("old")
    assert resolution.profile_exists("new")


def test_rename_default_protected(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("default")
    rc = cli.main(["rename", "default", "renamed"])
    assert rc == 2


def test_rename_collision_returns_2(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    manager.create_profile("a")
    manager.create_profile("b")
    rc = cli.main(["rename", "a", "b"])
    assert rc == 2


def test_rename_missing_returns_2(
    isolated_home: Path, capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["rename", "ghost", "new"])
    assert rc == 2
