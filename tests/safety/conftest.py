"""Shared safety fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def snapshot_root(tmp_path: Path) -> Path:
    """Isolated snapshot root under tmp_path so tests can't escape
    into the real ~/.athena/snapshots."""
    return tmp_path / "snapshots"
