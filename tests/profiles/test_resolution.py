"""Active profile resolution + bootstrap."""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.profiles import resolution


@pytest.fixture(autouse=True)
def isolated_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Redirect CONFIG_DIR-derived paths to tmp_path so tests can't
    escape into the real ~/.athena."""
    home = tmp_path / "athena_home"
    home.mkdir()
    monkeypatch.setattr(resolution, "PROFILES_DIR", home / "profiles")
    monkeypatch.setattr(
        resolution,
        "ACTIVE_PROFILE_FILE",
        home / "active_profile",
    )
    # Clear env so existing developer ATHENA_PROFILE doesn't leak in.
    monkeypatch.delenv("ATHENA_PROFILE", raising=False)
    monkeypatch.delenv("OCODE_PROFILE", raising=False)
    return home


# ---- name validation ------------------------------------------------


def test_valid_simple_name() -> None:
    assert resolution.is_valid_profile_name("default") is True
    assert resolution.is_valid_profile_name("work") is True
    assert resolution.is_valid_profile_name("personal-1") is True
    assert resolution.is_valid_profile_name("a") is True


def test_valid_with_underscore_and_hyphen() -> None:
    assert resolution.is_valid_profile_name("my_work_2") is True
    assert resolution.is_valid_profile_name("client-acme") is True


def test_reject_uppercase() -> None:
    assert resolution.is_valid_profile_name("Default") is False
    assert resolution.is_valid_profile_name("WORK") is False


def test_reject_path_traversal() -> None:
    assert resolution.is_valid_profile_name("../etc") is False
    assert resolution.is_valid_profile_name("a/b") is False
    assert resolution.is_valid_profile_name("a\\b") is False


def test_reject_special_chars() -> None:
    for bad in (" ", "a b", "a.b", "a$b", "a;b", "a|b", "a:b", "a*b"):
        assert resolution.is_valid_profile_name(bad) is False


def test_reject_empty() -> None:
    assert resolution.is_valid_profile_name("") is False


def test_reject_leading_hyphen_or_underscore() -> None:
    """Must start with alphanumeric — no -prefix / _prefix which look
    like CLI flags or hidden files."""
    assert resolution.is_valid_profile_name("-work") is False
    assert resolution.is_valid_profile_name("_work") is False


def test_reject_too_long() -> None:
    assert resolution.is_valid_profile_name("a" * 65) is False


def test_reject_non_string() -> None:
    assert resolution.is_valid_profile_name(None) is False  # type: ignore[arg-type]
    assert resolution.is_valid_profile_name(42) is False  # type: ignore[arg-type]


# ---- profile_dir / profile_exists / ensure --------------------------


def test_profile_dir_returns_path_under_profiles_dir(
    isolated_home: Path,
) -> None:
    p = resolution.profile_dir("work")
    assert p == isolated_home / "profiles" / "work"


def test_profile_dir_rejects_invalid_name() -> None:
    with pytest.raises(ValueError):
        resolution.profile_dir("Work")


def test_profile_exists_true_after_mkdir(isolated_home: Path) -> None:
    p = isolated_home / "profiles" / "work"
    p.mkdir(parents=True)
    assert resolution.profile_exists("work") is True


def test_profile_exists_false_when_missing(isolated_home: Path) -> None:
    assert resolution.profile_exists("ghost") is False


def test_profile_exists_false_for_invalid_name() -> None:
    """Soft test — invalid name returns False rather than raising."""
    assert resolution.profile_exists("../etc") is False


def test_ensure_profile_creates_layout(isolated_home: Path) -> None:
    root = resolution.ensure_profile("work")
    assert root == isolated_home / "profiles" / "work"
    assert (root / "skills").is_dir()
    assert (root / "memory").is_dir()
    assert (root / "sessions").is_dir()


def test_ensure_profile_idempotent(isolated_home: Path) -> None:
    resolution.ensure_profile("work")
    # Second call must not raise.
    resolution.ensure_profile("work")


# ---- resolve_active_profile ------------------------------------------


def test_default_when_nothing_set(isolated_home: Path) -> None:
    assert resolution.resolve_active_profile() == "default"


def test_cli_arg_wins_over_everything(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATHENA_PROFILE", "env-profile")
    resolution.set_active_profile_file("file-profile")
    result = resolution.resolve_active_profile(
        cli_arg="cli-profile",
        config_default="config-profile",
    )
    assert result == "cli-profile"


def test_env_beats_active_file_and_config(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATHENA_PROFILE", "env-profile")
    resolution.set_active_profile_file("file-profile")
    result = resolution.resolve_active_profile(
        config_default="config-profile",
    )
    assert result == "env-profile"


def test_legacy_ocode_profile_env_var_honored(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCODE_PROFILE", "legacy")
    assert resolution.resolve_active_profile() == "legacy"


def test_active_file_when_no_cli_or_env(isolated_home: Path) -> None:
    resolution.set_active_profile_file("written")
    assert resolution.resolve_active_profile() == "written"


def test_config_when_no_cli_env_or_file(isolated_home: Path) -> None:
    result = resolution.resolve_active_profile(config_default="cfg-profile")
    assert result == "cfg-profile"


def test_invalid_cli_falls_through(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user typing `athena --profile 'has spaces'` should land on
    env / file / default, not crash."""
    resolution.set_active_profile_file("file-profile")
    result = resolution.resolve_active_profile(cli_arg="bad name")
    assert result == "file-profile"


def test_invalid_env_falls_through(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATHENA_PROFILE", "Bad Name")
    resolution.set_active_profile_file("file-profile")
    assert resolution.resolve_active_profile() == "file-profile"


def test_empty_active_file_falls_through(isolated_home: Path) -> None:
    """An empty file (e.g. truncated to zero by a buggy editor) must
    not return ``""`` — fall through to the next source."""
    resolution.ACTIVE_PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    resolution.ACTIVE_PROFILE_FILE.write_text("", encoding="utf-8")
    assert resolution.resolve_active_profile(config_default="cfg") == "cfg"


def test_whitespace_only_active_file_falls_through(
    isolated_home: Path,
) -> None:
    resolution.ACTIVE_PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    resolution.ACTIVE_PROFILE_FILE.write_text("   \n  ", encoding="utf-8")
    assert resolution.resolve_active_profile() == "default"


# ---- set_active_profile_file / clear --------------------------------


def test_set_active_profile_file_is_atomic(isolated_home: Path) -> None:
    resolution.set_active_profile_file("work")
    # No leftover .tmp file.
    leftovers = list(
        resolution.ACTIVE_PROFILE_FILE.parent.glob("active_profile.tmp"),
    )
    assert leftovers == []
    assert resolution.ACTIVE_PROFILE_FILE.read_text() == "work"


def test_set_active_profile_file_rejects_invalid(
    isolated_home: Path,
) -> None:
    with pytest.raises(ValueError):
        resolution.set_active_profile_file("Bad")


def test_clear_active_profile_file_removes_it(
    isolated_home: Path,
) -> None:
    resolution.set_active_profile_file("work")
    assert resolution.ACTIVE_PROFILE_FILE.exists()
    resolution.clear_active_profile_file()
    assert not resolution.ACTIVE_PROFILE_FILE.exists()


def test_clear_when_missing_is_noop(isolated_home: Path) -> None:
    # No exception.
    resolution.clear_active_profile_file()
