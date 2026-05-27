"""Tests for the ``/board clear`` subcommand.

Lets the user nuke leftover aspirational tasks the model invented in a
prior session. Without this, accumulated cruft in the task store
re-enters context on every reload and pollutes prompts.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.commands.board import cmd_board


@pytest.fixture
def stub_env(tmp_path: Path, monkeypatch):
    """Point athena's load_config + profile_dir at a clean tmp tree so
    the real ``~/.athena`` is never touched.

    cmd_board uses lazy imports inside the function body — by patching
    the module attributes BEFORE the call, the function's
    ``from ..config import …`` resolves to the patched versions.
    """
    from athena.config import Config

    cfg = Config()
    cfg.profile = "default"

    pdir = tmp_path / "profile"
    pdir.mkdir()

    def _fake_load_config():
        return cfg

    def _fake_profile_dir(name, *, home=None):
        return pdir

    monkeypatch.setattr("athena.config.load_config", _fake_load_config)
    monkeypatch.setattr("athena.config.profile_dir", _fake_profile_dir)

    return SimpleNamespace(cfg=cfg, pdir=pdir)


def _populate(pdir: Path, n: int = 3):
    """Drop ``n`` tasks into the live store so /board clear has work to do."""
    from athena.config import Config
    from athena.tasks.model import TaskStore, default_task_store_path

    cfg = Config()
    cfg.profile = "default"
    store = TaskStore(path=default_task_store_path(cfg, pdir))
    for i in range(n):
        store.create(title=f"leftover task #{i}")
    return store


def test_board_clear_removes_all_live_tasks(stub_env):
    _populate(stub_env.pdir, n=3)

    cmd_board(SimpleNamespace(), "clear")

    # Reload from disk to confirm the wipe persisted.
    from athena.config import Config
    from athena.tasks.model import TaskStore, default_task_store_path

    cfg = Config()
    cfg.profile = "default"
    store = TaskStore(path=default_task_store_path(cfg, stub_env.pdir))
    assert store.all() == []


def test_board_clear_on_empty_board_is_safe(stub_env):
    """No tasks → /board clear should not raise."""
    cmd_board(SimpleNamespace(), "clear")
    # Reaching here without exception is the assertion.


def test_board_clear_with_all_flag_treated_same(stub_env):
    """``/board clear --all`` reserved for future per-goal scoping;
    today it behaves identically to bare clear."""
    _populate(stub_env.pdir, n=2)
    cmd_board(SimpleNamespace(), "clear --all")

    from athena.config import Config
    from athena.tasks.model import TaskStore, default_task_store_path

    cfg = Config()
    cfg.profile = "default"
    store = TaskStore(path=default_task_store_path(cfg, stub_env.pdir))
    assert store.all() == []


def test_board_clear_returns_empty_string(stub_env):
    """Like every other /board path, returns "" — no synthetic turn fires."""
    _populate(stub_env.pdir, n=1)
    result = cmd_board(SimpleNamespace(), "clear")
    assert result == ""


def test_board_default_path_unchanged(stub_env):
    """The non-clear paths (bare /board, /board goal:X) still render."""
    # _resolve_state will fire; just make sure no exception leaks out.
    result = cmd_board(SimpleNamespace(), "")
    assert result == ""
