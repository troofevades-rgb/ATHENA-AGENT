"""Migration of legacy flat layout to profiles/default/."""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.profiles import migration, resolution


@pytest.fixture
def fake_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Redirect CONFIG_DIR-derived state to tmp_path."""
    home = tmp_path / "athena_home"
    home.mkdir()
    monkeypatch.setattr(resolution, "PROFILES_DIR", home / "profiles")
    monkeypatch.setattr(
        resolution,
        "ACTIVE_PROFILE_FILE",
        home / "active_profile",
    )
    # migration.run_migration takes the home path as an arg, so
    # passing tmp_path directly works without monkey-patching
    # athena.config.CONFIG_DIR — but maybe_run_migration uses the
    # default if no home passed, so patch that path too.
    monkeypatch.setattr(migration, "CONFIG_DIR", home)
    return home


def _seed_legacy(home: Path, items: list[str]) -> None:
    """Populate ``home`` with the named files/dirs (mix is fine)."""
    for item in items:
        if "." in item and not item.endswith("/"):
            (home / item).write_text(f"<{item} content>", encoding="utf-8")
        else:
            (home / item).mkdir(parents=True, exist_ok=True)
            # Leave a marker file inside so we can verify it survives
            # the move.
            (home / item / "marker.txt").write_text(
                "marker",
                encoding="utf-8",
            )


# ---- migration_needed ---------------------------------------------


def test_migration_needed_when_legacy_items_exist(fake_home: Path) -> None:
    _seed_legacy(fake_home, ["skills", "sessions.db"])
    assert migration.migration_needed(fake_home) is True


def test_migration_not_needed_when_profiles_dir_exists(
    fake_home: Path,
) -> None:
    """Once profiles/ exists, migration is permanently done."""
    _seed_legacy(fake_home, ["skills"])
    (fake_home / "profiles").mkdir()
    assert migration.migration_needed(fake_home) is False


def test_migration_not_needed_on_fresh_install(fake_home: Path) -> None:
    """Empty home (no legacy items) → no migration."""
    assert migration.migration_needed(fake_home) is False


def test_migration_only_triggered_by_profile_items(fake_home: Path) -> None:
    """A global-only item (credentials.json, plugins/) doesn't trigger
    migration — those stay at the top level."""
    (fake_home / "credentials.json").write_text("{}", encoding="utf-8")
    (fake_home / "plugins").mkdir()
    assert migration.migration_needed(fake_home) is False


# ---- run_migration ------------------------------------------------


def test_run_migration_moves_skills(fake_home: Path) -> None:
    (fake_home / "skills" / "my-skill").mkdir(parents=True)
    (fake_home / "skills" / "my-skill" / "SKILL.md").write_text(
        "x",
        encoding="utf-8",
    )
    result = migration.run_migration(fake_home)
    assert "skills" in result["moved"]
    assert (fake_home / "profiles" / "default" / "skills" / "my-skill" / "SKILL.md").exists()
    assert not (fake_home / "skills").exists()


def test_run_migration_moves_files(fake_home: Path) -> None:
    (fake_home / "config.toml").write_text(
        "model = 'qwen2.5'",
        encoding="utf-8",
    )
    (fake_home / "sessions.db").write_text("binary", encoding="utf-8")
    migration.run_migration(fake_home)
    assert (fake_home / "profiles" / "default" / "config.toml").read_text() == "model = 'qwen2.5'"
    assert (fake_home / "profiles" / "default" / "sessions.db").exists()


def test_run_migration_preserves_global_items(fake_home: Path) -> None:
    """credentials.json / plugins / etc. stay at top level."""
    (fake_home / "credentials.json").write_text("{}", encoding="utf-8")
    (fake_home / "plugins").mkdir()
    (fake_home / "logs").mkdir()
    (fake_home / "mcp_tokens").mkdir()
    # Also a profile-level item to actually trigger the move.
    (fake_home / "skills").mkdir()
    migration.run_migration(fake_home)
    # Globals untouched.
    assert (fake_home / "credentials.json").exists()
    assert (fake_home / "plugins").is_dir()
    assert (fake_home / "logs").is_dir()
    assert (fake_home / "mcp_tokens").is_dir()


def test_run_migration_ensures_default_layout(fake_home: Path) -> None:
    """Even when nothing moves, the default profile's bootstrap dirs
    must exist after migration."""
    migration.run_migration(fake_home)
    default = fake_home / "profiles" / "default"
    assert (default / "skills").is_dir()
    assert (default / "memory").is_dir()
    assert (default / "sessions").is_dir()


def test_run_migration_idempotent(fake_home: Path) -> None:
    """Calling twice is safe — second call moves nothing."""
    _seed_legacy(fake_home, ["skills"])
    first = migration.run_migration(fake_home)
    assert "skills" in first["moved"]
    second = migration.run_migration(fake_home)
    assert second["moved"] == []


def test_run_migration_skips_collision(fake_home: Path) -> None:
    """If the target already has a same-named entry (partial prior
    migration), don't clobber. Log it as failed and move on."""
    (fake_home / "skills").mkdir()
    (fake_home / "skills" / "marker.txt").write_text("from-legacy")
    # Pre-create a conflicting destination.
    target = fake_home / "profiles" / "default" / "skills"
    target.mkdir(parents=True)
    (target / "marker.txt").write_text("already-here", encoding="utf-8")

    result = migration.run_migration(fake_home)
    assert "skills" in result["failed"]
    # Existing content preserved.
    assert (target / "marker.txt").read_text() == "already-here"
    # Source still on disk for manual resolution.
    assert (fake_home / "skills" / "marker.txt").exists()


def test_run_migration_per_item_isolation(
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure on one item must not block the others."""
    _seed_legacy(fake_home, ["skills", "memory"])

    real_move = migration.shutil.move
    moved_args: list[str] = []

    def maybe_failing_move(src: str, dst: str) -> str:
        moved_args.append(src)
        if "skills" in src:
            raise OSError("simulated failure")
        return real_move(src, dst)

    monkeypatch.setattr(migration.shutil, "move", maybe_failing_move)
    result = migration.run_migration(fake_home)
    assert "memory" in result["moved"]
    assert "skills" in result["failed"]


# ---- maybe_run_migration ----------------------------------------


def test_maybe_run_migration_triggers_on_legacy(fake_home: Path) -> None:
    _seed_legacy(fake_home, ["skills"])
    assert migration.maybe_run_migration(fake_home) is True
    assert (fake_home / "profiles" / "default" / "skills").exists()


def test_maybe_run_migration_skips_when_not_needed(fake_home: Path) -> None:
    assert migration.maybe_run_migration(fake_home) is False
    # No profiles dir spawned either.
    assert not (fake_home / "profiles").exists()


def test_maybe_run_migration_idempotent(fake_home: Path) -> None:
    _seed_legacy(fake_home, ["skills"])
    assert migration.maybe_run_migration(fake_home) is True
    assert migration.maybe_run_migration(fake_home) is False
