"""Tests for the workspace-keyed legacy memory API.

``athena.memory.__init__`` exports the functions the agent still uses
to inject ``MEMORY.md`` into the system prompt every session:

  * ``load_memory_index(workspace)`` — what becomes the system-prompt
    memory block.
  * ``list_memories(workspace)`` / ``parse_memory_file(path)`` —
    what ``/memory list/show`` reads.
  * ``write_memory(...)`` / ``delete_memory(...)`` — what
    ``/memory save/delete`` calls.
  * ``_slugify`` / ``memory_dir`` — workspace identity.

These have NO direct test file today (only indirect coverage via
``tests/commands/test_memory_command.py``). If any of this regresses,
the symptom is silent: the system prompt loads the wrong memory,
includes nothing, or — worst — includes another workspace's memory.

The Phase 14 migration to the profile-keyed provider API is planned
but not done; until then this is the load-bearing surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import athena.memory as legacy_mem
from athena.memory import (
    MemoryFile,
    _slugify,
    delete_memory,
    list_memories,
    load_memory_index,
    memory_dir,
    parse_memory_file,
    write_memory,
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp workspace + isolated PROJECTS_DIR so tests can't escape
    to the developer's real ~/.athena/projects."""
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(legacy_mem, "PROJECTS_DIR", tmp_path / "projects")
    return ws


# ---------------------------------------------------------------------------
# _slugify + memory_dir — workspace identity
# ---------------------------------------------------------------------------


def test_slugify_is_stable_across_calls() -> None:
    """Same input → same output across calls. If this regresses, every
    restart picks a NEW slug and the user's memory disappears."""
    p = Path("/some/workspace/path")
    s1 = _slugify(p)
    s2 = _slugify(p)
    assert s1 == s2


def test_slugify_distinct_paths_with_same_letterform_dont_collide(
    tmp_path: Path,
) -> None:
    """``/a/b-c`` and ``/a/b/c`` slugify to similar strings but the
    hash suffix keeps them distinct. Without that, two unrelated
    projects would share a memory dir."""
    a = tmp_path / "b-c"
    b = tmp_path / "b" / "c"
    a.mkdir()
    b.mkdir(parents=True)
    assert _slugify(a) != _slugify(b)


def test_memory_dir_lives_under_projects_dir(
    workspace: Path,
) -> None:
    """The whole point of the slugify is that all per-workspace state
    lives under one PROJECTS_DIR root. Pin that."""
    d = memory_dir(workspace)
    assert legacy_mem.PROJECTS_DIR in d.parents
    assert d.name == "memory"


# ---------------------------------------------------------------------------
# load_memory_index — what the system prompt sees
# ---------------------------------------------------------------------------


def test_load_index_returns_none_when_no_memory_dir(workspace: Path) -> None:
    """Fresh workspace, no ~/.athena/projects/<slug>/memory yet —
    must return None (not crash, not empty string). The system prompt
    builder uses ``is not None`` to decide whether to inject the block."""
    assert load_memory_index(workspace) is None


def test_load_index_returns_none_for_whitespace_only_file(
    workspace: Path,
) -> None:
    """An empty or whitespace-only MEMORY.md should be treated as
    no-memory — otherwise the system prompt gets a useless empty
    block that wastes context."""
    d = memory_dir(workspace)
    d.mkdir(parents=True)
    (d / "MEMORY.md").write_text("\n   \n\t\n", encoding="utf-8")
    assert load_memory_index(workspace) is None


def test_load_index_truncates_at_200_lines(workspace: Path) -> None:
    """The agent system prompt has a strict 200-line cap (matching
    Claude Code). A user with a runaway MEMORY.md must not blow the
    context budget."""
    d = memory_dir(workspace)
    d.mkdir(parents=True)
    body = "\n".join(f"- line {i}" for i in range(250))
    (d / "MEMORY.md").write_text(body, encoding="utf-8")

    out = load_memory_index(workspace)
    assert out is not None
    out_lines = out.splitlines()
    # 200 original + 2 truncation marker lines = 202
    assert len(out_lines) == 202
    assert "line 199" in out_lines[199]  # last preserved
    assert "line 200" not in out
    assert "<!-- index truncated at 200 lines -->" in out


def test_load_index_under_200_lines_is_passed_through(
    workspace: Path,
) -> None:
    """Sub-200-line indexes must come back BYTE-FOR-BYTE unchanged
    (modulo final newline handling). The agent's system prompt
    relies on the exact text it sees."""
    d = memory_dir(workspace)
    d.mkdir(parents=True)
    original = "- [a](a.md) — note a\n- [b](b.md) — note b"
    (d / "MEMORY.md").write_text(original, encoding="utf-8")

    out = load_memory_index(workspace)
    assert out == original


def test_load_index_handles_unreadable_file_without_crashing(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file that exists but raises OSError on read (perms, deleted
    mid-read on POSIX) must return None — must not propagate to
    the system prompt build path."""
    d = memory_dir(workspace)
    d.mkdir(parents=True)
    p = d / "MEMORY.md"
    p.write_text("x", encoding="utf-8")

    real_read = Path.read_text
    def _boom(self, *a, **kw):
        if self == p:
            raise OSError("simulated")
        return real_read(self, *a, **kw)
    monkeypatch.setattr(Path, "read_text", _boom)

    assert load_memory_index(workspace) is None


# ---------------------------------------------------------------------------
# parse_memory_file — frontmatter parsing
# ---------------------------------------------------------------------------


def test_parse_handles_normal_frontmatter(tmp_path: Path) -> None:
    p = tmp_path / "good.md"
    p.write_text(
        "---\nname: Test\ndescription: a thing\ntype: user\n---\n\nbody here\n",
        encoding="utf-8",
    )
    mf = parse_memory_file(p)
    assert mf is not None
    assert mf.name == "Test"
    assert mf.description == "a thing"
    assert mf.type == "user"
    assert mf.body == "body here"


def test_parse_handles_quoted_frontmatter_values(tmp_path: Path) -> None:
    """YAML-style single/double-quoted values must round-trip
    unquoted. Quoted strings are common when the value contains
    colons or special chars."""
    p = tmp_path / "q.md"
    p.write_text(
        '---\nname: "Quoted: thing"\ndescription: \'also quoted\'\ntype: user\n---\n\nb\n',
        encoding="utf-8",
    )
    mf = parse_memory_file(p)
    assert mf is not None
    assert mf.name == "Quoted: thing"
    assert mf.description == "also quoted"


def test_parse_returns_none_for_missing_frontmatter(tmp_path: Path) -> None:
    """Files without ---...--- block are not memories. Must return
    None silently (list_memories filters these out)."""
    p = tmp_path / "plain.md"
    p.write_text("just some markdown\n", encoding="utf-8")
    assert parse_memory_file(p) is None


def test_parse_returns_none_for_unreadable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OSError on read → None, no exception. list_memories iterates
    a dir and a single bad file must not break the whole listing."""
    p = tmp_path / "ghost.md"
    p.write_text("---\nname: x\n---\nb\n", encoding="utf-8")

    real_read = Path.read_text
    def _boom(self, *a, **kw):
        if self == p:
            raise OSError("simulated")
        return real_read(self, *a, **kw)
    monkeypatch.setattr(Path, "read_text", _boom)

    assert parse_memory_file(p) is None


def test_parse_defaults_to_user_type_when_omitted(tmp_path: Path) -> None:
    """If frontmatter omits ``type``, default to 'user' — preserves
    backwards compatibility with hand-written memories that pre-date
    the type taxonomy."""
    p = tmp_path / "typeless.md"
    p.write_text(
        "---\nname: legacy\ndescription: from before types\n---\n\nb\n",
        encoding="utf-8",
    )
    mf = parse_memory_file(p)
    assert mf is not None
    assert mf.type == "user"


# ---------------------------------------------------------------------------
# write_memory — round-trip + index refresh
# ---------------------------------------------------------------------------


def test_write_then_load_round_trip(workspace: Path) -> None:
    """The basic recovery contract — what you write is what
    list_memories sees after."""
    write_memory(
        workspace,
        filename="user_role",
        name="user role",
        description="senior eng",
        type="user",
        body="The user is a senior engineer working on athena.",
    )
    mems = list_memories(workspace)
    assert len(mems) == 1
    assert mems[0].name == "user role"
    assert mems[0].type == "user"
    assert "senior engineer" in mems[0].body


def test_write_refreshes_memory_md_index(workspace: Path) -> None:
    """After write, MEMORY.md must contain a one-line pointer to
    the new file. Without this the system prompt never references
    the new memory."""
    write_memory(
        workspace,
        filename="proj_alpha",
        name="alpha project",
        description="hook line",
        type="project",
        body="b",
    )
    index = load_memory_index(workspace)
    assert index is not None
    assert "alpha project" in index
    assert "proj_alpha.md" in index
    assert "project" in index


def test_write_rejects_invalid_type(workspace: Path) -> None:
    """Only user|feedback|project|reference are allowed. A typo
    like 'note' or 'misc' must fail fast at write time, not
    silently corrupt the file."""
    with pytest.raises(ValueError, match="invalid memory type"):
        write_memory(
            workspace, filename="x", name="x", description="x",
            type="note", body="b",
        )


def test_write_rejects_memory_md_filename(workspace: Path) -> None:
    """MEMORY.md is the index, not a memory. Allowing a memory
    named MEMORY.md would silently clobber the index on the next
    refresh and lose ALL the user's other memories."""
    with pytest.raises(ValueError, match="MEMORY.md"):
        write_memory(
            workspace, filename="MEMORY.md", name="x",
            description="x", type="user", body="b",
        )


def test_write_auto_appends_md_suffix(workspace: Path) -> None:
    """User-friendly: ``filename='my_note'`` writes my_note.md."""
    p = write_memory(
        workspace, filename="my_note", name="n",
        description="d", type="user", body="b",
    )
    assert p.suffix == ".md"
    assert p.name == "my_note.md"


def test_write_overwrites_existing_memory_with_same_filename(
    workspace: Path,
) -> None:
    """``/memory save`` to an existing slug updates. Pin this — if
    it ever flips to append, the file format breaks."""
    write_memory(
        workspace, filename="role", name="v1",
        description="first", type="user", body="initial body",
    )
    write_memory(
        workspace, filename="role", name="v2",
        description="second", type="user", body="updated body",
    )
    mems = list_memories(workspace)
    assert len(mems) == 1
    assert mems[0].name == "v2"
    assert mems[0].body == "updated body"


# ---------------------------------------------------------------------------
# delete_memory — index refresh after delete
# ---------------------------------------------------------------------------


def test_delete_returns_false_when_file_missing(workspace: Path) -> None:
    assert delete_memory(workspace, "never_existed.md") is False


def test_delete_removes_file_and_index_entry(workspace: Path) -> None:
    """After delete, both the .md file AND its MEMORY.md row must
    be gone. A stale index row pointing to a missing file would
    confuse the agent (Read errors mid-session)."""
    write_memory(
        workspace, filename="temp", name="t",
        description="will be removed", type="user", body="b",
    )
    assert (memory_dir(workspace) / "temp.md").exists()
    assert "temp.md" in (load_memory_index(workspace) or "")

    assert delete_memory(workspace, "temp.md") is True
    assert not (memory_dir(workspace) / "temp.md").exists()
    assert "temp.md" not in (load_memory_index(workspace) or "")


# ---------------------------------------------------------------------------
# Cross-workspace isolation
# ---------------------------------------------------------------------------


def test_two_workspaces_get_independent_memory_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A memory written in workspace A must not appear in workspace
    B. The slug guarantees this; if it ever regresses, projects
    bleed memories into each other."""
    monkeypatch.setattr(legacy_mem, "PROJECTS_DIR", tmp_path / "projects")
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()

    write_memory(
        ws_a, filename="secret", name="A-only",
        description="should never appear in B", type="user", body="b",
    )

    assert len(list_memories(ws_a)) == 1
    assert list_memories(ws_b) == []
    assert load_memory_index(ws_b) is None


# ---------------------------------------------------------------------------
# Path traversal — security
# ---------------------------------------------------------------------------


def test_filename_with_path_traversal_is_rejected_or_contained(
    workspace: Path, tmp_path: Path,
) -> None:
    """A filename like '../escape' MUST NOT write outside the
    memory dir. The agent (with the model's judgement) is the
    caller of write_memory via the /memory save handler — a
    prompt-injection that nudges the model to use a bad filename
    is a real threat.

    Acceptable outcomes:
      (a) write_memory raises ValueError on the bad filename, OR
      (b) the resulting file lives strictly inside memory_dir.

    This test catches either silent escape or silent breakage."""
    mem_d = memory_dir(workspace)
    sentinel = tmp_path / "should_not_be_written"

    try:
        result = write_memory(
            workspace, filename="../should_not_be_written",
            name="bad", description="bad", type="user", body="x",
        )
    except (ValueError, OSError):
        # Accepted outcome (a)
        assert not sentinel.exists()
        return

    # Accepted outcome (b): the file IS written, but inside memory_dir
    assert mem_d in result.resolve().parents or mem_d == result.resolve().parent, (
        f"path traversal succeeded: file landed at {result} which is "
        f"outside memory_dir {mem_d}. Prompt-injection could write "
        f"arbitrary files."
    )
    assert not sentinel.exists(), (
        f"escape file written at {sentinel} — write_memory does not "
        f"sanitize ../ in filenames"
    )


# ---------------------------------------------------------------------------
# list_memories — directory walk semantics
# ---------------------------------------------------------------------------


def test_list_skips_non_md_files(workspace: Path) -> None:
    """Stray files in the memory dir (.DS_Store, swap files, the
    user dropping a note) must not show up as memories."""
    d = memory_dir(workspace)
    d.mkdir(parents=True)
    (d / "notes.txt").write_text("not a memory", encoding="utf-8")
    (d / ".DS_Store").write_bytes(b"\x00\x00")
    write_memory(
        workspace, filename="real", name="r",
        description="d", type="user", body="b",
    )

    mems = list_memories(workspace)
    assert len(mems) == 1
    assert mems[0].name == "r"


def test_list_skips_memory_md_itself(workspace: Path) -> None:
    """MEMORY.md is the index — it must never show up as a memory
    in its own listing."""
    write_memory(
        workspace, filename="x", name="x",
        description="d", type="user", body="b",
    )
    mems = list_memories(workspace)
    assert all(m.path.name != "MEMORY.md" for m in mems)


def test_list_filters_out_unparseable_files(workspace: Path) -> None:
    """A .md file with no frontmatter isn't a memory — must not
    surface in the listing (and must not crash it either)."""
    d = memory_dir(workspace)
    d.mkdir(parents=True)
    (d / "garbage.md").write_text("no frontmatter here\n", encoding="utf-8")
    write_memory(
        workspace, filename="real", name="r",
        description="d", type="user", body="b",
    )

    mems = list_memories(workspace)
    names = {m.path.name for m in mems}
    assert "garbage.md" not in names
    assert "real.md" in names


def test_list_returns_empty_for_missing_workspace(workspace: Path) -> None:
    """No memory_dir yet → empty list, no exception. The agent's
    system prompt build path calls list_memories unconditionally."""
    assert list_memories(workspace) == []
