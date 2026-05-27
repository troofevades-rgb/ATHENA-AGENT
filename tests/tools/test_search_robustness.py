"""Glob and Grep must tolerate per-directory I/O errors.

On Windows, a single subdirectory whose filename can't round-trip
through scandir (Cyrillic / mangled UTF-8) makes pathlib.Path.glob()
crash for the WHOLE search. _safe_walk swallows those errors so the
rest of the tree still gets searched.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from athena.tools import file_ops
from athena.tools.search import Glob, Grep, _match_glob_pattern, _safe_walk


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch):
    """A small workspace with a normal file and one "broken" dir we
    simulate by raising OSError from os.scandir."""
    (tmp_path / "good_file.py").write_text("hello = 1\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "another.py").write_text("world = 2\n", encoding="utf-8")
    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)
    return tmp_path


# ----------------------------------------------------------------------
# Robustness: scandir errors don't kill the whole search
# ----------------------------------------------------------------------


def test_glob_skips_unreadable_directory(workspace, monkeypatch):
    """Simulate a poisoned dir by patching os.walk's onerror path."""
    real_walk = os.walk

    def _walk_with_one_error(root, onerror=None):
        # Yield normal entries, then call onerror once (as if a real
        # scandir failed), then keep going.
        for entry in real_walk(root, onerror=onerror):
            yield entry
        if onerror is not None:
            onerror(OSError("simulated bad directory"))

    monkeypatch.setattr("athena.tools.search.os.walk", _walk_with_one_error)

    out = Glob("**/*.py")
    # The good files should still be found.
    assert "good_file.py" in out
    assert "nested/another.py" in out or "nested\\another.py" in out


def test_grep_python_fallback_skips_unreadable_directory(workspace, monkeypatch):
    monkeypatch.setattr("athena.tools.search._HAS_RG", False)
    real_walk = os.walk

    def _walk_with_one_error(root, onerror=None):
        for entry in real_walk(root, onerror=onerror):
            yield entry
        if onerror is not None:
            onerror(OSError("simulated"))

    monkeypatch.setattr("athena.tools.search.os.walk", _walk_with_one_error)

    out = Grep("hello")
    assert "hello = 1" in out


# ----------------------------------------------------------------------
# _safe_walk yields the expected files in a normal tree
# ----------------------------------------------------------------------


def test_safe_walk_yields_all_files(workspace):
    files = sorted(p.name for p in _safe_walk(workspace))
    assert files == ["another.py", "good_file.py"]


def test_safe_walk_handles_empty_dir(tmp_path):
    out = list(_safe_walk(tmp_path))
    assert out == []


# ----------------------------------------------------------------------
# Pattern matching covers the cases the model uses
# ----------------------------------------------------------------------


def test_match_glob_pattern_simple():
    assert _match_glob_pattern("foo.py", "*.py")
    assert not _match_glob_pattern("foo.py", "*.ts")


def test_match_glob_pattern_recursive():
    assert _match_glob_pattern("src/lib/foo.py", "**/*.py")
    assert _match_glob_pattern("a/b/c.py", "**/*.py")
    assert _match_glob_pattern("a/b/c.py", "a/**/*.py")


def test_match_glob_pattern_normalizes_separators():
    """Windows paths use backslash; pattern matching should DTRT."""
    assert _match_glob_pattern("src\\foo.py", "src/*.py")


# ----------------------------------------------------------------------
# End-to-end: Glob finds nested files via **
# ----------------------------------------------------------------------


def test_glob_matches_nested(workspace):
    out = Glob("**/*.py")
    assert "good_file.py" in out
    # Forward slashes in the relative path output.
    assert "another.py" in out


def test_glob_specific_subdir(workspace):
    out = Glob("nested/*.py")
    assert "another.py" in out
    assert "good_file.py" not in out


def test_glob_no_matches(workspace):
    out = Glob("**/*.nonexistent")
    assert out == "(no matches)"
