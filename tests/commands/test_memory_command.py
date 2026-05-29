"""Tests for ``/memory`` — list / show / delete / dir.

The command thinly wraps ``athena.memory``: we mock each of the
memory module's exports and verify the command's routing logic
(arg parsing, error messages, calls into memory with the right
workspace).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from athena.commands.memory import cmd_memory


def _capture():
    lines: list[str] = []
    patches = []
    for fn in ("info", "warn", "error"):
        patches.append(
            patch(
                f"athena.commands.memory.ui.{fn}",
                side_effect=lambda msg, *a, _n=fn, **kw:
                    lines.append(f"{_n}: {msg}"),
            )
        )
    patches.append(
        patch(
            "athena.commands.memory.ui.console.print",
            side_effect=lambda *a, **kw:
                lines.append(" ".join(str(x) for x in a)),
        )
    )
    return lines, patches


def _run(agent, arg: str) -> str:
    lines, patches = _capture()
    for p in patches:
        p.start()
    try:
        cmd_memory(agent, arg)
    finally:
        for p in patches:
            p.stop()
    return "\n".join(lines)


def _agent(workspace: Path) -> SimpleNamespace:
    return SimpleNamespace(workspace=workspace)


def _mem(name: str, *, type: str = "fact", description: str = "", path: Path = None) -> SimpleNamespace:
    """Build a fake memory-file record matching what list_memories returns."""
    return SimpleNamespace(
        name=name,
        type=type,
        description=description,
        path=path or Path(f"/fake/{name}.md"),
        body="",
    )


# ---- /memory (no arg) / /memory list -------------------------------


def test_no_arg_lists_memories(tmp_path: Path) -> None:
    mems = [
        _mem("api-keys", description="API tokens"),
        _mem("conventions", type="preference", description="Code style"),
    ]
    with patch(
        "athena.commands.memory.list_memories", return_value=mems,
    ), patch(
        "athena.commands.memory.memory_dir",
        return_value=tmp_path / "memory",
    ):
        out = _run(_agent(tmp_path), "")
    assert "api-keys" in out
    assert "conventions" in out
    assert "API tokens" in out
    assert "Code style" in out
    # Type tags rendered
    assert "fact" in out
    assert "preference" in out


def test_no_arg_with_no_memories_shows_dir() -> None:
    """When the workspace has no memories, surface the dir path
    so the user knows where to drop one."""
    fake_dir = Path("/fake/memdir")
    with patch(
        "athena.commands.memory.list_memories", return_value=[],
    ), patch(
        "athena.commands.memory.memory_dir", return_value=fake_dir,
    ):
        out = _run(_agent(Path("/ws")), "")
    assert "no memories" in out.lower()
    assert str(fake_dir) in out


def test_explicit_list_subcommand_works() -> None:
    """``/memory list`` should behave identically to bare ``/memory``."""
    with patch(
        "athena.commands.memory.list_memories",
        return_value=[_mem("only-one")],
    ), patch(
        "athena.commands.memory.memory_dir", return_value=Path("/m"),
    ):
        out = _run(_agent(Path("/ws")), "list")
    assert "only-one" in out


# ---- /memory show <file> -------------------------------------------


def test_show_without_filename_errors() -> None:
    with patch(
        "athena.commands.memory.parse_memory_file"
    ) as parse:
        out = _run(_agent(Path("/ws")), "show")
    parse.assert_not_called()
    assert "usage" in out.lower()
    assert "show" in out


def test_show_renders_memory_body() -> None:
    fake = SimpleNamespace(
        path=Path("/m/api.md"),
        name="api-keys",
        type="fact",
        description="API tokens we care about",
        body="API_KEY=xxx\nOTHER=yyy",
    )
    with patch(
        "athena.commands.memory.memory_dir",
        return_value=Path("/m"),
    ), patch(
        "athena.commands.memory.parse_memory_file",
        return_value=fake,
    ):
        out = _run(_agent(Path("/ws")), "show api.md")
    assert "api-keys" in out
    assert "fact" in out
    assert "API tokens we care about" in out
    assert "API_KEY=xxx" in out
    assert "OTHER=yyy" in out


def test_show_unparseable_errors() -> None:
    """parse_memory_file returning None means the file doesn't exist
    or has bad frontmatter — surface a friendly error, not a crash."""
    with patch(
        "athena.commands.memory.memory_dir",
        return_value=Path("/m"),
    ), patch(
        "athena.commands.memory.parse_memory_file",
        return_value=None,
    ):
        out = _run(_agent(Path("/ws")), "show bogus.md")
    assert "not found or unparseable" in out.lower()


# ---- /memory delete <file> -----------------------------------------


def test_delete_without_filename_errors() -> None:
    with patch(
        "athena.commands.memory.delete_memory"
    ) as del_mock:
        out = _run(_agent(Path("/ws")), "delete")
    del_mock.assert_not_called()
    assert "usage" in out.lower()
    assert "delete" in out


def test_delete_success_path() -> None:
    """delete_memory returning True means deletion succeeded."""
    with patch(
        "athena.commands.memory.delete_memory", return_value=True,
    ):
        out = _run(_agent(Path("/ws")), "delete obsolete.md")
    # No error message
    assert "error" not in out.lower()
    assert "not found" not in out.lower()


def test_delete_missing_file_errors() -> None:
    """delete_memory returning False means it wasn't there — error
    surface should match."""
    with patch(
        "athena.commands.memory.delete_memory", return_value=False,
    ):
        out = _run(_agent(Path("/ws")), "delete missing.md")
    assert "not found" in out.lower()


# ---- /memory dir ---------------------------------------------------


def test_dir_prints_memory_directory_path() -> None:
    target = Path("/some/profile/memory")
    with patch(
        "athena.commands.memory.memory_dir", return_value=target,
    ):
        out = _run(_agent(Path("/ws")), "dir")
    assert str(target) in out


# ---- unknown subcommand --------------------------------------------


def test_unknown_subcommand_errors() -> None:
    out = _run(_agent(Path("/ws")), "frobnicate")
    assert "unknown subcommand" in out.lower()
    # Helper message tells user the valid options
    assert "list" in out
    assert "show" in out
    assert "delete" in out
    assert "dir" in out
