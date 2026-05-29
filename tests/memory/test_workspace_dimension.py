"""R2 stage 1 -- BuiltinFileProvider workspace dimension.

Pins the new ``workspace=`` kwarg on every public method:

  - ``workspace=None`` keeps the single-store-per-profile layout
    (``<profile_dir>/memory/``) that MCP server tools and the
    ``athena memory`` CLI use today.
  - ``workspace=<path>`` selects a workspace-scoped sub-store at
    ``<profile_dir>/memory/legacy/<workspace-slug>/`` so the
    R2-stage-2 agent read path can isolate per-workspace memories
    under the active profile (mirrors the legacy
    ``~/.athena/projects/<slug>/memory/`` shape).

Slug stability matters for the R2-stage-4 data migration: the
``workspace_slug`` helper must produce byte-identical output to
the legacy ``athena.memory._slugify``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.memory.providers.builtin_file import BuiltinFileProvider
from athena.memory.store import (
    delete_entry,
    list_entries,
    load_index,
    query,
    read_entry,
    write_entry,
)


@pytest.fixture
def provider(tmp_path: Path) -> BuiltinFileProvider:
    return BuiltinFileProvider(home=tmp_path / "fake-home")


# ---------------------------------------------------------------------------
# Slug stability + algorithm contract
# ---------------------------------------------------------------------------


def test_workspace_slug_is_stable_across_calls(tmp_path: Path) -> None:
    """``BuiltinFileProvider.workspace_slug`` must be deterministic:
    calling it twice on the same path yields the same slug. The
    on-disk layout depends on this -- a drifting slug would leave
    each session writing to a fresh sub-store."""
    for ws in [tmp_path, tmp_path / "nested", Path.home() / "projects" / "x"]:
        assert BuiltinFileProvider.workspace_slug(ws) == BuiltinFileProvider.workspace_slug(ws)


def test_workspace_slug_ends_with_eight_hex_hash(tmp_path: Path) -> None:
    """The algorithm appends an 8-char SHA-1 prefix so distinct paths
    with the same letterform stay distinct. Pin the suffix shape so a
    refactor of the slug function gets caught -- existing on-disk data
    would silently strand otherwise."""
    import re

    slug = BuiltinFileProvider.workspace_slug(tmp_path / "ws")
    assert re.search(r"_[0-9a-f]{8}$", slug), f"slug {slug!r} lost its hash suffix"


def test_workspace_slug_distinguishes_collision_paths(tmp_path: Path) -> None:
    """Two paths that share a letterform after slash-replacement (e.g.
    ``/a/b-c`` and ``/a/b/c``) must still produce distinct slugs --
    otherwise distinct workspaces would share a memory dir."""
    a = tmp_path / "a-b"
    b = tmp_path / "a" / "b"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert BuiltinFileProvider.workspace_slug(a) != BuiltinFileProvider.workspace_slug(b)


# ---------------------------------------------------------------------------
# Layout -- workspace=None vs workspace=<path>
# ---------------------------------------------------------------------------


def test_workspace_none_keeps_classic_layout(provider, tmp_path: Path) -> None:
    """``workspace=None`` writes under ``<profile_dir>/memory/`` --
    the existing single-store-per-profile shape."""
    path = provider.write_entry(
        "default",
        filename="alpha.md",
        name="alpha",
        description="d",
        type="user",
        body="b",
        write_origin="foreground",
    )
    expected_parent = tmp_path / "fake-home" / "profiles" / "default" / "memory"
    assert path.parent == expected_parent
    assert path.name == "alpha.md"


def test_workspace_lands_under_legacy_subdir(provider, tmp_path: Path) -> None:
    """``workspace=<path>`` writes under
    ``<profile_dir>/memory/legacy/<workspace-slug>/`` so distinct
    workspaces under the same profile stay isolated."""
    workspace = tmp_path / "ws-a"
    workspace.mkdir()
    path = provider.write_entry(
        "default",
        filename="alpha.md",
        name="alpha",
        description="d",
        type="user",
        body="b",
        write_origin="foreground",
        workspace=workspace,
    )
    slug = BuiltinFileProvider.workspace_slug(workspace)
    expected_parent = (
        tmp_path
        / "fake-home"
        / "profiles"
        / "default"
        / "memory"
        / "legacy"
        / slug
    )
    assert path.parent == expected_parent


# ---------------------------------------------------------------------------
# Isolation -- different workspaces, different profiles
# ---------------------------------------------------------------------------


def test_distinct_workspaces_have_distinct_stores(provider, tmp_path: Path) -> None:
    ws_a = tmp_path / "ws-a"
    ws_b = tmp_path / "ws-b"
    ws_a.mkdir()
    ws_b.mkdir()

    provider.write_entry(
        "default",
        filename="only_a.md",
        name="only_a",
        description="d",
        type="user",
        body="b",
        write_origin="foreground",
        workspace=ws_a,
    )

    assert [e.name for e in provider.list_entries("default", workspace=ws_a)] == ["only_a"]
    assert provider.list_entries("default", workspace=ws_b) == []


def test_workspace_isolated_from_classic_store(provider, tmp_path: Path) -> None:
    """A workspace-scoped write must NOT appear in the classic
    (``workspace=None``) listing -- distinct sub-stores."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    provider.write_entry(
        "default",
        filename="ws_only.md",
        name="ws_only",
        description="d",
        type="user",
        body="b",
        write_origin="foreground",
        workspace=workspace,
    )
    assert [e.name for e in provider.list_entries("default")] == []
    assert [e.name for e in provider.list_entries("default", workspace=workspace)] == [
        "ws_only"
    ]


def test_same_workspace_isolated_across_profiles(provider, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    provider.write_entry(
        "alpha",
        filename="entry.md",
        name="alpha_entry",
        description="d",
        type="user",
        body="b",
        write_origin="foreground",
        workspace=workspace,
    )
    assert [
        e.name for e in provider.list_entries("alpha", workspace=workspace)
    ] == ["alpha_entry"]
    assert provider.list_entries("beta", workspace=workspace) == []


# ---------------------------------------------------------------------------
# Every public method threads workspace correctly
# ---------------------------------------------------------------------------


def test_read_and_delete_honour_workspace(provider, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    provider.write_entry(
        "default",
        filename="x.md",
        name="x",
        description="d",
        type="user",
        body="needle here",
        write_origin="foreground",
        workspace=workspace,
    )
    # read_entry honors workspace.
    entry = provider.read_entry("default", "x", workspace=workspace)
    assert entry is not None and entry.body.startswith("needle here")
    assert provider.read_entry("default", "x") is None  # classic store empty

    # query honors workspace.
    hits = provider.query("default", query="needle", k=5, workspace=workspace)
    assert [h.name for h in hits] == ["x"]
    assert provider.query("default", query="needle", k=5) == []

    # delete_entry honors workspace.
    assert provider.delete_entry("default", "x", workspace=workspace) is True
    assert provider.list_entries("default", workspace=workspace) == []


def test_load_index_honours_workspace(provider, tmp_path: Path) -> None:
    """``load_index`` returns MEMORY.md for the (profile, workspace)
    pair -- distinct workspaces produce distinct indices."""
    ws_a = tmp_path / "ws-a"
    ws_a.mkdir()
    provider.write_entry(
        "default",
        filename="entry.md",
        name="entry_a",
        description="d",
        type="user",
        body="b",
        write_origin="foreground",
        workspace=ws_a,
    )
    idx_a = provider.load_index("default", workspace=ws_a)
    assert idx_a is not None and "entry_a" in idx_a
    # Classic store has nothing -> None.
    assert provider.load_index("default") is None


# ---------------------------------------------------------------------------
# Façade in athena.memory.store mirrors the kwarg
# ---------------------------------------------------------------------------


def test_store_facade_threads_workspace_kwarg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``athena.memory.store.{write_entry,list_entries,...}`` accepts
    ``workspace=`` and forwards it to the active provider. Pinned via
    the real BuiltinFileProvider rooted under a tmp home."""
    fake_home = tmp_path / "fake-home"
    monkeypatch.setattr(
        "athena.memory.store.get_provider",
        lambda name="builtin_file": BuiltinFileProvider(home=fake_home),
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    write_entry(
        "default",
        filename="thing.md",
        name="thing",
        description="d",
        type="user",
        body="b",
        write_origin="foreground",
        workspace=workspace,
    )
    assert [e.name for e in list_entries("default", workspace=workspace)] == ["thing"]
    assert list_entries("default") == []
    assert read_entry("default", "thing", workspace=workspace) is not None
    assert read_entry("default", "thing") is None
    assert query("default", query="b", k=5, workspace=workspace)
    assert query("default", query="b", k=5) == []
    idx = load_index("default", workspace=workspace)
    assert idx is not None and "thing" in idx
    assert load_index("default") is None
    assert delete_entry("default", "thing", workspace=workspace) is True
