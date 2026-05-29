"""R2 stage 4 -- workspace-keyed legacy memory -> profile sub-store.

Pins :func:`athena.profiles.migration.migrate_workspace_memory` and
its convenience wrapper :func:`maybe_migrate_workspace_memory`:

  * Source layout: ``<home>/projects/<workspace-slug>/memory/`` (the
    pre-R2 store every athena release wrote to).
  * Target layout: ``<profile_dir>/memory/legacy/<workspace-slug>/``
    (the R2 stage-1 sub-store the new provider reads from).
  * Idempotent: re-running is a no-op (skips when target exists).
  * Flag-gated: the wrapper does nothing when
    ``cfg.migrate_legacy_memory`` is False (the default during the
    R2 dogfood window).
  * Per-workspace: only the requested workspace's slug migrates;
    sibling workspaces stay where they are until each runs through
    its own session.
  * ``dry_run=True`` reports what would copy without touching disk.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.memory.providers.builtin_file import BuiltinFileProvider
from athena.profiles import migration


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tmp home; matches the production layout the migrator targets.

    Production paths under ``home``:
      - ``home/projects/<slug>/memory/`` -- legacy source.
      - ``home/profiles/<profile>/memory/legacy/<slug>/`` -- new target.

    The :func:`athena.config.profile_dir` helper resolves
    ``<home>/profiles/<profile>`` so the migrator and the provider
    share a single source of truth for the target.
    """
    home = tmp_path / "home"
    home.mkdir()
    return home


@pytest.fixture
def short_slug(monkeypatch: pytest.MonkeyPatch) -> str:
    """Pin a short slug to dodge Windows MAX_PATH (260 chars). The
    real algorithm is exercised in
    ``tests/memory/test_workspace_dimension.py``."""
    slug = "ws-stub"
    monkeypatch.setattr(
        BuiltinFileProvider,
        "workspace_slug",
        staticmethod(lambda _ws: slug),
    )
    return slug


def _seed_legacy(home: Path, slug: str, files: dict[str, str]) -> Path:
    """Populate ``<home>/projects/<slug>/memory/`` with given files."""
    src = home / "projects" / slug / "memory"
    src.mkdir(parents=True)
    for name, content in files.items():
        (src / name).write_text(content, encoding="utf-8")
    return src


# ---------------------------------------------------------------------------
# Core migration shape
# ---------------------------------------------------------------------------


def test_migrate_copies_all_files(
    fake_home: Path, short_slug: str, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    src = _seed_legacy(
        fake_home,
        short_slug,
        {
            "MEMORY.md": "# MEMORY index\n\n- [alpha](alpha.md) — user: greeting\n",
            "alpha.md": "---\nname: alpha\ndescription: greeting\ntype: user\n---\n\nhello\n",
            "feedback_x.md": "---\nname: feedback_x\ndescription: care\ntype: feedback\n---\n\nbody\n",
        },
    )

    summary = migration.migrate_workspace_memory(
        profile="default", workspace=workspace, home=fake_home
    )

    assert summary["ran"] is True
    assert set(summary["copied"]) == {"MEMORY.md", "alpha.md", "feedback_x.md"}
    assert summary["skipped"] == []

    target = fake_home / "profiles" / "default" / "memory" / "legacy" / short_slug
    assert target.is_dir()
    assert (target / "MEMORY.md").read_text(encoding="utf-8").startswith("# MEMORY index")
    assert "hello" in (target / "alpha.md").read_text(encoding="utf-8")
    # Source intact (copy, not move) so the stage-2 fallback in
    # ``agent/core.py`` keeps working until R2 stage 5.
    assert (src / "alpha.md").exists()


def test_migrate_is_noop_when_source_missing(
    fake_home: Path, short_slug: str, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    summary = migration.migrate_workspace_memory(
        profile="default", workspace=workspace, home=fake_home
    )
    assert summary["ran"] is False
    assert summary["copied"] == []


def test_migrate_skips_when_target_already_exists(
    fake_home: Path, short_slug: str, tmp_path: Path
) -> None:
    """Idempotency guard -- re-running on a session whose target
    already exists must not re-copy (and must not raise) so the
    opportunistic call from ``Agent.__init__`` stays cheap."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_legacy(fake_home, short_slug, {"alpha.md": "---\nname: alpha\ndescription: x\ntype: user\n---\n\nb\n"})

    # First run migrates.
    first = migration.migrate_workspace_memory(
        profile="default", workspace=workspace, home=fake_home
    )
    assert first["ran"] is True

    # Drop a marker into the target -- the second run must NOT clobber it.
    target = fake_home / "profiles" / "default" / "memory" / "legacy" / short_slug
    (target / "USER_TOUCHED.md").write_text("don't touch", encoding="utf-8")

    second = migration.migrate_workspace_memory(
        profile="default", workspace=workspace, home=fake_home
    )
    assert second["ran"] is False
    assert second["copied"] == []
    assert (target / "USER_TOUCHED.md").read_text(encoding="utf-8") == "don't touch"


def test_migrate_dry_run_reports_without_writing(
    fake_home: Path, short_slug: str, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_legacy(
        fake_home,
        short_slug,
        {"alpha.md": "---\nname: alpha\ndescription: x\ntype: user\n---\n\nb\n"},
    )

    summary = migration.migrate_workspace_memory(
        profile="default", workspace=workspace, home=fake_home, dry_run=True
    )
    assert summary["ran"] is True
    assert summary["copied"] == ["alpha.md"]
    target = fake_home / "profiles" / "default" / "memory" / "legacy" / short_slug
    assert not target.exists(), "dry_run must not touch disk"


def test_migrate_only_touches_requested_workspace(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two workspaces under the same profile each have their own
    legacy dir. Migrating one must leave the sibling untouched until
    its own session runs."""

    # Slug is derived from the workspace path here, so we use a custom
    # static slug function that distinguishes the two.
    def _slug(ws: Path) -> str:
        return f"slug-{ws.name}"

    monkeypatch.setattr(
        BuiltinFileProvider, "workspace_slug", staticmethod(_slug)
    )

    ws_a = tmp_path / "ws-a"
    ws_a.mkdir()
    ws_b = tmp_path / "ws-b"
    ws_b.mkdir()
    _seed_legacy(fake_home, _slug(ws_a), {"a.md": "---\nname: a\ndescription: x\ntype: user\n---\n\nA\n"})
    _seed_legacy(fake_home, _slug(ws_b), {"b.md": "---\nname: b\ndescription: x\ntype: user\n---\n\nB\n"})

    migration.migrate_workspace_memory(
        profile="default", workspace=ws_a, home=fake_home
    )

    target_a = fake_home / "profiles" / "default" / "memory" / "legacy" / _slug(ws_a)
    target_b = fake_home / "profiles" / "default" / "memory" / "legacy" / _slug(ws_b)
    assert (target_a / "a.md").exists()
    assert not target_b.exists(), "sibling workspace migrated unexpectedly"


# ---------------------------------------------------------------------------
# maybe_migrate_workspace_memory -- the flag-gated convenience wrapper
# ---------------------------------------------------------------------------


def test_maybe_migrate_off_by_default(
    fake_home: Path, short_slug: str, tmp_path: Path
) -> None:
    """Without ``cfg.migrate_legacy_memory = True`` the wrapper must
    be a no-op -- session starts during the dogfood window stay
    free of disk side-effects."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_legacy(fake_home, short_slug, {"alpha.md": "---\nname: alpha\ndescription: x\ntype: user\n---\n\nb\n"})

    cfg = SimpleNamespace(profile="default", migrate_legacy_memory=False)
    result = migration.maybe_migrate_workspace_memory(cfg, workspace)
    assert result is None
    target = fake_home / "profiles" / "default" / "memory" / "legacy" / short_slug
    assert not target.exists()


def test_maybe_migrate_runs_when_flag_set(
    fake_home: Path,
    short_slug: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag flipped -> wrapper calls migrate_workspace_memory with
    (profile, workspace)."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_legacy(fake_home, short_slug, {"alpha.md": "---\nname: alpha\ndescription: x\ntype: user\n---\n\nb\n"})

    monkeypatch.setattr(migration, "CONFIG_DIR", fake_home)

    cfg = SimpleNamespace(profile="default", migrate_legacy_memory=True)
    result = migration.maybe_migrate_workspace_memory(cfg, workspace)
    assert result is not None
    assert result["ran"] is True
    assert "alpha.md" in result["copied"]
