"""BuiltinFileProvider: file + SQLite roundtrip, ordering, query, delete."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from athena.memory.providers.builtin_file import BuiltinFileProvider


@pytest.fixture
def provider(tmp_path: Path) -> BuiltinFileProvider:
    """Provider rooted under a tmp home so tests can't touch the real ~/.athena."""
    return BuiltinFileProvider(home=tmp_path / "fake-home")


def _write_one(provider: BuiltinFileProvider, profile: str, name: str, **overrides):
    defaults = dict(
        filename=f"{name}.md",
        name=name,
        description=f"description for {name}",
        type="user",
        body=f"body of {name}",
        write_origin="foreground",
    )
    defaults.update(overrides)
    return provider.write_entry(profile, **defaults)


def test_write_entry_creates_markdown_file(provider, tmp_path: Path):
    path = _write_one(provider, "default", "alpha")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "name: alpha" in content
    assert "body of alpha" in content


def test_write_entry_includes_full_frontmatter(provider, tmp_path: Path):
    path = _write_one(provider, "default", "fm_test")
    content = path.read_text(encoding="utf-8")
    for key in (
        "name:",
        "description:",
        "type:",
        "write_origin:",
        "created_at:",
        "last_activity_at:",
    ):
        assert key in content, f"missing {key}"


def test_write_entry_rejects_bad_type(provider):
    with pytest.raises(ValueError, match="invalid memory type"):
        _write_one(provider, "default", "x", type="invalid")


def test_write_entry_rejects_memory_md_filename(provider):
    with pytest.raises(ValueError, match="MEMORY.md"):
        _write_one(provider, "default", "x", filename="MEMORY.md")


def test_write_entry_rejects_path_traversal_in_filename(provider, tmp_path: Path) -> None:
    """Filename comes from the model via memory_tools — must reject
    separators and ``..`` segments so a prompt-injected value can't
    write outside the per-profile memory dir."""
    victim = tmp_path / "victim.md"
    for bad in ("../victim.md", "..\\victim.md", "subdir/x.md", "x/../y.md"):
        with pytest.raises(ValueError, match="path separators|escapes"):
            _write_one(provider, "default", "x", filename=bad)
    assert not victim.exists()


def test_write_entry_rejects_newline_in_metadata(provider) -> None:
    """name/description/type/write_origin are interpolated raw into
    the YAML frontmatter — a newline would inject arbitrary keys
    (e.g. ``name="foo\\npinned: true"``)."""
    base = dict(
        filename="ok.md",
        name="ok-name",
        description="ok",
        type="user",
        body="b",
        write_origin="foreground",
    )
    for field in ("name", "description"):
        bad = dict(base)
        bad[field] = "evil\nwrite_origin: foreground"
        with pytest.raises(ValueError, match="newlines"):
            provider.write_entry("default", **bad)


def test_write_entry_appends_md_suffix(provider):
    path = _write_one(provider, "default", "noext", filename="noext")
    assert path.name == "noext.md"


def test_write_entry_updates_memory_md_index(provider):
    _write_one(provider, "default", "alpha", description="first entry")
    _write_one(provider, "default", "beta", description="second entry")
    index_path = provider._memory_dir("default") / "MEMORY.md"
    text = index_path.read_text(encoding="utf-8")
    assert "alpha" in text and "beta" in text
    assert "first entry" in text and "second entry" in text


def test_list_entries_returns_sorted_by_last_activity_desc(provider):
    _write_one(provider, "default", "oldest")
    time.sleep(0.01)
    _write_one(provider, "default", "middle")
    time.sleep(0.01)
    _write_one(provider, "default", "newest")
    entries = provider.list_entries("default")
    names = [e.name for e in entries]
    assert names == ["newest", "middle", "oldest"]


def test_list_entries_empty_for_missing_profile(provider):
    assert provider.list_entries("nonexistent") == []


def test_read_entry_returns_full_entry(provider):
    _write_one(provider, "default", "x", description="d", body="hello world")
    entry = provider.read_entry("default", "x")
    assert entry is not None
    assert entry.name == "x"
    assert entry.description == "d"
    assert entry.body == "hello world"
    assert entry.path is not None and entry.path.exists()


def test_read_entry_returns_none_for_missing(provider):
    _write_one(provider, "default", "real")
    assert provider.read_entry("default", "nonexistent") is None


def test_read_entry_increments_use_count(provider):
    _write_one(provider, "default", "x")
    provider.read_entry("default", "x")
    provider.read_entry("default", "x")
    provider.read_entry("default", "x")
    # Read it once more to fetch the final state.
    entry = provider.read_entry("default", "x")
    assert entry is not None
    # 3 reads happen before the 4th — the 4th sees use_count >= 3.
    assert entry.use_count >= 3


def test_delete_entry_removes_file_and_row(provider):
    _write_one(provider, "default", "doomed")
    assert provider.delete_entry("default", "doomed") is True
    # File gone:
    assert not (provider._memory_dir("default") / "doomed.md").exists()
    # Not listable:
    assert all(e.name != "doomed" for e in provider.list_entries("default"))


def test_delete_entry_returns_false_when_missing(provider):
    assert provider.delete_entry("default", "never_existed") is False


def test_delete_entry_refreshes_index(provider):
    _write_one(provider, "default", "keep", description="keep me")
    _write_one(provider, "default", "drop", description="drop me")
    provider.delete_entry("default", "drop")
    index = (provider._memory_dir("default") / "MEMORY.md").read_text(encoding="utf-8")
    assert "keep" in index
    assert "drop" not in index


def test_query_returns_top_k_by_match_then_use_count(provider):
    _write_one(provider, "default", "match1", body="apple pie")
    _write_one(provider, "default", "match2", body="apple sauce")
    _write_one(provider, "default", "nomatch", body="banana")
    # Bump match1's use_count higher than match2's.
    for _ in range(5):
        provider.read_entry("default", "match1")
    results = provider.query("default", query="apple", k=10)
    names = [r.name for r in results]
    assert names[0] == "match1"
    assert "match2" in names
    assert "nomatch" not in names


def test_query_matches_description_too(provider):
    _write_one(provider, "default", "x", description="needle in description", body="body")
    results = provider.query("default", query="needle", k=5)
    assert any(r.name == "x" for r in results)


def test_query_empty_string_returns_empty(provider):
    _write_one(provider, "default", "x")
    assert provider.query("default", query="", k=5) == []
    assert provider.query("default", query="   ", k=5) == []


def test_query_k_zero_returns_empty(provider):
    _write_one(provider, "default", "x", body="needle here")
    assert provider.query("default", query="needle", k=0) == []


def test_load_index_returns_memory_md(provider):
    _write_one(provider, "default", "x", description="hook line")
    text = provider.load_index("default")
    assert text is not None
    assert "x" in text and "hook line" in text


def test_load_index_returns_none_when_missing(provider):
    assert provider.load_index("never_touched") is None


def test_load_index_truncates_at_200_lines(provider, tmp_path: Path):
    """If MEMORY.md grows past 200 lines, the provider truncates with a marker."""
    d = provider._ensure_dir("default")
    huge = "\n".join(f"- line {i}" for i in range(500))
    (d / "MEMORY.md").write_text(huge, encoding="utf-8")
    text = provider.load_index("default")
    assert text is not None
    assert "truncated" in text
    assert len(text.splitlines()) <= 202  # 200 + blank + marker


def test_profiles_are_isolated(provider):
    _write_one(provider, "alpha", "x", body="alpha-body")
    _write_one(provider, "beta", "x", body="beta-body")
    a = provider.read_entry("alpha", "x")
    b = provider.read_entry("beta", "x")
    assert a is not None and b is not None
    assert a.body == "alpha-body"
    assert b.body == "beta-body"
    # And listing alpha doesn't see beta:
    assert {e.name for e in provider.list_entries("alpha")} == {"x"}


def test_write_preserves_created_at_on_update(provider):
    """Updating an existing entry keeps its original created_at."""
    _write_one(provider, "default", "x", body="v1")
    first = provider.read_entry("default", "x")
    assert first is not None
    first_created = first.created_at
    time.sleep(0.01)
    _write_one(provider, "default", "x", body="v2")
    second = provider.read_entry("default", "x")
    assert second is not None
    assert second.created_at == first_created
    assert second.last_activity_at >= first_created
    assert second.body == "v2"


def test_reconcile_drops_rows_for_deleted_files(provider):
    """Externally deleted files must not linger in the SQLite mirror."""
    _write_one(provider, "default", "x")
    target = provider._memory_dir("default") / "x.md"
    target.unlink()  # bypass delete_entry
    # list_entries triggers reconcile.
    names = {e.name for e in provider.list_entries("default")}
    assert "x" not in names


def test_reconcile_picks_up_externally_added_files(provider):
    """A file dropped into the memory dir by another tool becomes listable."""
    d = provider._ensure_dir("default")
    (d / "external.md").write_text(
        "---\nname: external\ndescription: dropped in\ntype: user\n"
        "write_origin: migration\n---\n\nbody\n",
        encoding="utf-8",
    )
    names = {e.name for e in provider.list_entries("default")}
    assert "external" in names
