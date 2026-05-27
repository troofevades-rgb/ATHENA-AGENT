"""Regression: ``_resolve_store`` must rebuild when the resolved
path changes between calls.

The bug: the original implementation cached the first store in a
module-level ``_store`` and returned it unconditionally on every
subsequent call. In tests that monkeypatched ``profile_dir`` to a
``tmp_path``, the first call (before the patch was active —
typically during collection or an earlier test) cached a store
pointing at the real ``~/.athena/profiles/default/tasks/tasks.json``.
Every TaskCreate call inside the patched test then wrote into the
USER'S real board, with the test's ``tmp_path`` as the
``workspace`` field. Over many CI / dev runs this accumulated
hundreds of orphan cards on the user's daily board, which the
agent then dragged back into context every session.

The fix: rebuild when ``_store.path != newly-resolved path``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _reset_module_cache():
    """Each test starts with a clean module-level cache."""
    from athena.tools import task as task_mod

    saved = task_mod._store
    task_mod._store = None
    yield
    task_mod._store = saved


def test_store_rebuilds_when_profile_dir_changes(
    tmp_path: Path, monkeypatch
):
    """First resolve at path A; monkeypatch profile_dir to path B;
    next resolve must yield a store pointing at B, not the cached A."""
    from athena.tools import task as task_mod

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    monkeypatch.setattr("athena.config.profile_dir", lambda *a_, **kw: a)
    store_a = task_mod._resolve_store()
    assert store_a.path.is_relative_to(a)

    monkeypatch.setattr("athena.config.profile_dir", lambda *a_, **kw: b)
    store_b = task_mod._resolve_store()
    assert store_b.path.is_relative_to(b), (
        "stale cache leaked a store from a prior profile_dir — would "
        "silently route TaskCreate writes into the user's real board"
    )
    assert store_a is not store_b


def test_store_is_cached_when_path_unchanged(
    tmp_path: Path, monkeypatch
):
    """Production hot path: path is stable, so we MUST return the
    same instance — avoids re-reading the JSON on every TaskCreate."""
    from athena.tools import task as task_mod

    monkeypatch.setattr(
        "athena.config.profile_dir", lambda *a, **kw: tmp_path
    )
    first = task_mod._resolve_store()
    second = task_mod._resolve_store()
    assert first is second
