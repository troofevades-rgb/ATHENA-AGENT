"""Profile lifecycle — list, create, delete, switch, rename."""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.profiles import manager, resolution


@pytest.fixture(autouse=True)
def isolated_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    home = tmp_path / "athena_home"
    home.mkdir()
    monkeypatch.setattr(resolution, "PROFILES_DIR", home / "profiles")
    monkeypatch.setattr(
        resolution,
        "ACTIVE_PROFILE_FILE",
        home / "active_profile",
    )
    monkeypatch.setattr(manager, "PROFILES_DIR", home / "profiles")
    monkeypatch.setattr(
        manager,
        "ACTIVE_PROFILE_FILE",
        home / "active_profile",
    )
    monkeypatch.delenv("ATHENA_PROFILE", raising=False)
    return home


# ---- list -----------------------------------------------------------


def test_list_empty_when_no_profiles_dir(isolated_home: Path) -> None:
    assert manager.list_profiles() == []


def test_list_returns_sorted(isolated_home: Path) -> None:
    resolution.ensure_profile("work")
    resolution.ensure_profile("default")
    resolution.ensure_profile("client-acme")
    assert manager.list_profiles() == ["client-acme", "default", "work"]


def test_list_skips_invalid_names(isolated_home: Path) -> None:
    """Stray files / invalid-named dirs in profiles/ don't appear."""
    (isolated_home / "profiles").mkdir()
    (isolated_home / "profiles" / "default").mkdir()
    (isolated_home / "profiles" / "Has Spaces").mkdir()
    (isolated_home / "profiles" / "stray-file.txt").write_text("x")
    assert manager.list_profiles() == ["default"]


# ---- create --------------------------------------------------------


def test_create_profile_bootstraps_layout(isolated_home: Path) -> None:
    path = manager.create_profile("work")
    assert path == isolated_home / "profiles" / "work"
    assert (path / "skills").is_dir()
    assert (path / "memory").is_dir()
    assert (path / "sessions").is_dir()
    assert (path / "config.toml").is_file()


def test_create_default_config_toml_is_non_empty_template(
    isolated_home: Path,
) -> None:
    path = manager.create_profile("work")
    body = (path / "config.toml").read_text(encoding="utf-8")
    # The template includes guidance comments.
    assert "#" in body
    assert len(body) > 50  # not empty / placeholder


def test_create_invalid_name_raises(isolated_home: Path) -> None:
    with pytest.raises(ValueError):
        manager.create_profile("Bad Name")


def test_create_existing_raises(isolated_home: Path) -> None:
    manager.create_profile("work")
    with pytest.raises(FileExistsError):
        manager.create_profile("work")


def test_create_with_copy_from(isolated_home: Path) -> None:
    src = manager.create_profile("work")
    # Pre-populate the source with something unique so we can verify
    # the copy worked.
    (src / "skills" / "my-skill").mkdir()
    (src / "skills" / "my-skill" / "SKILL.md").write_text(
        "---\nname: my-skill\n---\n",
        encoding="utf-8",
    )
    (src / "memory" / "notes.md").write_text("private", encoding="utf-8")

    dest = manager.create_profile("work-copy", copy_from="work")
    assert (dest / "skills" / "my-skill" / "SKILL.md").exists()
    assert (dest / "memory" / "notes.md").read_text() == "private"


def test_create_copy_from_unknown_source_raises(isolated_home: Path) -> None:
    with pytest.raises(FileNotFoundError):
        manager.create_profile("work", copy_from="missing")


def test_create_copy_from_invalid_source_name_raises(
    isolated_home: Path,
) -> None:
    with pytest.raises(ValueError):
        manager.create_profile("work", copy_from="Has Spaces")


# ---- delete --------------------------------------------------------


def test_delete_requires_token_match(isolated_home: Path) -> None:
    manager.create_profile("work")
    with pytest.raises(ValueError):
        manager.delete_profile("work", confirm_token="not-work")
    # Still on disk.
    assert (isolated_home / "profiles" / "work").exists()


def test_delete_with_matching_token_removes(isolated_home: Path) -> None:
    manager.create_profile("work")
    manager.delete_profile("work", confirm_token="work")
    assert not (isolated_home / "profiles" / "work").exists()


def test_cannot_delete_default(isolated_home: Path) -> None:
    manager.create_profile("default")
    with pytest.raises(ValueError, match="default"):
        manager.delete_profile("default", confirm_token="default")
    assert (isolated_home / "profiles" / "default").exists()


def test_delete_missing_profile_is_idempotent(isolated_home: Path) -> None:
    # No exception.
    manager.delete_profile("ghost", confirm_token="ghost")


def test_delete_invalid_name_raises(isolated_home: Path) -> None:
    with pytest.raises(ValueError):
        manager.delete_profile("Bad", confirm_token="Bad")


def test_delete_clears_active_profile_if_pointed_at_target(
    isolated_home: Path,
) -> None:
    manager.create_profile("work")
    manager.switch_profile("work")
    assert resolution.ACTIVE_PROFILE_FILE.read_text() == "work"
    manager.delete_profile("work", confirm_token="work")
    assert not resolution.ACTIVE_PROFILE_FILE.exists()


def test_delete_keeps_active_profile_for_unrelated_target(
    isolated_home: Path,
) -> None:
    manager.create_profile("work")
    manager.create_profile("other")
    manager.switch_profile("work")
    manager.delete_profile("other", confirm_token="other")
    assert resolution.ACTIVE_PROFILE_FILE.read_text() == "work"


# ---- switch --------------------------------------------------------


def test_switch_writes_active_file(isolated_home: Path) -> None:
    manager.create_profile("work")
    manager.switch_profile("work")
    assert resolution.ACTIVE_PROFILE_FILE.read_text() == "work"


def test_switch_to_nonexistent_raises(isolated_home: Path) -> None:
    with pytest.raises(FileNotFoundError):
        manager.switch_profile("ghost")
    assert not resolution.ACTIVE_PROFILE_FILE.exists()


def test_switch_to_invalid_name_raises_via_existence_check(
    isolated_home: Path,
) -> None:
    """Invalid name → profile_exists returns False → FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        manager.switch_profile("Bad Name")


# ---- rename --------------------------------------------------------


def test_rename_moves_directory(isolated_home: Path) -> None:
    manager.create_profile("old")
    manager.rename_profile("old", "new")
    assert (isolated_home / "profiles" / "new").exists()
    assert not (isolated_home / "profiles" / "old").exists()


def test_rename_cannot_rename_default(isolated_home: Path) -> None:
    manager.create_profile("default")
    with pytest.raises(ValueError, match="default"):
        manager.rename_profile("default", "renamed")


def test_rename_to_existing_raises(isolated_home: Path) -> None:
    manager.create_profile("a")
    manager.create_profile("b")
    with pytest.raises(FileExistsError):
        manager.rename_profile("a", "b")


def test_rename_invalid_names_raise(isolated_home: Path) -> None:
    manager.create_profile("ok")
    with pytest.raises(ValueError):
        manager.rename_profile("ok", "Bad")
    with pytest.raises(ValueError):
        manager.rename_profile("Bad", "ok2")


def test_rename_missing_source_raises(isolated_home: Path) -> None:
    with pytest.raises(FileNotFoundError):
        manager.rename_profile("ghost", "new")


def test_rename_updates_active_profile(isolated_home: Path) -> None:
    manager.create_profile("work")
    manager.switch_profile("work")
    manager.rename_profile("work", "work-renamed")
    assert resolution.ACTIVE_PROFILE_FILE.read_text() == "work-renamed"


def test_rename_preserves_active_profile_for_unrelated(
    isolated_home: Path,
) -> None:
    manager.create_profile("active")
    manager.create_profile("other")
    manager.switch_profile("active")
    manager.rename_profile("other", "other-renamed")
    assert resolution.ACTIVE_PROFILE_FILE.read_text() == "active"
