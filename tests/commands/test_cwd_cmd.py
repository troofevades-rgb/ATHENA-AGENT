"""Tests for ``/cwd [path]`` — show / change agent workspace."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from athena.commands.cwd_cmd import cmd_cwd


def _capture():
    lines: list[str] = []
    patches = []
    for fn in ("info", "warn", "error"):
        patches.append(
            patch(
                f"athena.commands.cwd_cmd.ui.{fn}",
                side_effect=lambda msg, *a, _n=fn, **kw:
                    lines.append(f"{_n}: {msg}"),
            )
        )
    return lines, patches


def _run(agent, arg: str) -> str:
    lines, patches = _capture()
    for p in patches:
        p.start()
    try:
        cmd_cwd(agent, arg)
    finally:
        for p in patches:
            p.stop()
    return "\n".join(lines)


def _fake_agent(workspace: Path) -> SimpleNamespace:
    """Minimal agent for /cwd tests. Workspace mutation paths replace
    messages[0] and call agent._build_system, so we stub all of those."""
    return SimpleNamespace(
        workspace=workspace,
        cfg=SimpleNamespace(max_file_read=64_000),
        messages=[{"role": "system", "content": "original"}],
        _build_system=lambda: "rebuilt-system",
    )


# ---- no arg: show current workspace ---------------------------------


def test_no_arg_shows_current_workspace(tmp_path: Path) -> None:
    agent = _fake_agent(tmp_path)
    out = _run(agent, "")
    assert str(tmp_path) in out
    assert "workspace" in out.lower()
    # No mutation occurred.
    assert agent.workspace == tmp_path
    assert agent.messages[0]["content"] == "original"


# ---- arg: switch workspace ------------------------------------------


def test_switch_to_existing_directory_updates_workspace(tmp_path: Path) -> None:
    """Successful switch must update agent.workspace, propagate to
    file_ops + hooks, and rebuild the system prompt in place."""
    agent = _fake_agent(tmp_path)
    new_dir = tmp_path / "subproject"
    new_dir.mkdir()

    set_ws_calls: list = []
    load_hooks_calls: list = []
    with patch(
        "athena.commands.cwd_cmd.tools.file_ops.set_workspace",
        side_effect=lambda p, max_read: set_ws_calls.append((p, max_read)),
    ), patch(
        "athena.commands.cwd_cmd.hooks_mod.load_hooks",
        side_effect=lambda p: load_hooks_calls.append(p),
    ):
        out = _run(agent, str(new_dir))

    assert agent.workspace == new_dir.resolve()
    assert set_ws_calls == [(new_dir.resolve(), 64_000)]
    assert load_hooks_calls == [new_dir.resolve()]
    # System message rebuilt
    assert agent.messages[0] == {"role": "system", "content": "rebuilt-system"}
    assert str(new_dir.resolve()) in out
    assert "system prompt rebuilt" in out
    assert "/clear" in out


def test_switch_expands_user_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``~/foo`` should expand before validation."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "homedir-target").mkdir()
    agent = _fake_agent(tmp_path)
    with patch("athena.commands.cwd_cmd.tools.file_ops.set_workspace"), \
         patch("athena.commands.cwd_cmd.hooks_mod.load_hooks"):
        _run(agent, "~/homedir-target")
    assert agent.workspace == (tmp_path / "homedir-target").resolve()


def test_switch_to_nonexistent_path_errors(tmp_path: Path) -> None:
    agent = _fake_agent(tmp_path)
    bogus = tmp_path / "does-not-exist"
    out = _run(agent, str(bogus))
    assert "not a directory" in out.lower()
    # No mutation
    assert agent.workspace == tmp_path
    assert agent.messages[0]["content"] == "original"


def test_switch_to_file_path_errors(tmp_path: Path) -> None:
    """A regular file is not a directory — refuse to switch."""
    agent = _fake_agent(tmp_path)
    file_path = tmp_path / "file.txt"
    file_path.write_text("not a dir")
    out = _run(agent, str(file_path))
    assert "not a directory" in out.lower()
    assert agent.workspace == tmp_path


def test_switch_handles_messages_without_system_prompt(tmp_path: Path) -> None:
    """The rebuild path guards on messages[0].role == 'system'. When
    history starts with a user message (e.g. after /resume), the cwd
    switch still succeeds — it just doesn't rebuild messages[0]."""
    agent = SimpleNamespace(
        workspace=tmp_path,
        cfg=SimpleNamespace(max_file_read=64_000),
        messages=[{"role": "user", "content": "first message"}],
        _build_system=lambda: "should-not-be-used",
    )
    new_dir = tmp_path / "another"
    new_dir.mkdir()
    with patch("athena.commands.cwd_cmd.tools.file_ops.set_workspace"), \
         patch("athena.commands.cwd_cmd.hooks_mod.load_hooks"):
        _run(agent, str(new_dir))
    # Workspace updated
    assert agent.workspace == new_dir.resolve()
    # Messages[0] untouched
    assert agent.messages[0] == {"role": "user", "content": "first message"}


def test_switch_handles_empty_messages(tmp_path: Path) -> None:
    """Edge case: empty messages list. Must not IndexError."""
    agent = SimpleNamespace(
        workspace=tmp_path,
        cfg=SimpleNamespace(max_file_read=64_000),
        messages=[],
        _build_system=lambda: "unused",
    )
    new_dir = tmp_path / "x"
    new_dir.mkdir()
    with patch("athena.commands.cwd_cmd.tools.file_ops.set_workspace"), \
         patch("athena.commands.cwd_cmd.hooks_mod.load_hooks"):
        _run(agent, str(new_dir))
    assert agent.workspace == new_dir.resolve()
