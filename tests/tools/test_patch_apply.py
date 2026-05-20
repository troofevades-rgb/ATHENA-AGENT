"""Integration tests for the patch_apply tool (T2-07.4).

Uses the autouse ``_path_security_workspace`` fixture from
tests/conftest.py to point validate_path at tmp_path so the tool's
writes don't need an approval prompt.
"""

from __future__ import annotations

from pathlib import Path

from athena.tools.patch_apply import patch_apply


def test_single_file_single_hunk_applied(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("line1\nline2\nline3\n")

    patch = f"""--- a/{f.as_posix()}
+++ b/{f.as_posix()}
@@ -1,3 +1,3 @@
 line1
-line2
+line2_changed
 line3
"""
    result = patch_apply(patch=patch)
    assert "applied 1 hunk" in result
    assert f.read_text() == "line1\nline2_changed\nline3\n"


def test_multi_hunk_atomically_applied(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n")
    patch = f"""--- a/{f.as_posix()}
+++ b/{f.as_posix()}
@@ -2,1 +2,1 @@
-b
+B
@@ -8,1 +8,1 @@
-h
+H
"""
    result = patch_apply(patch=patch)
    assert "applied 2 hunk" in result
    new = f.read_text().splitlines()
    assert new[1] == "B"
    assert new[7] == "H"


def test_multi_file_atomically_applied(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("hello\n")
    b.write_text("world\n")
    patch = f"""--- a/{a.as_posix()}
+++ b/{a.as_posix()}
@@ -1,1 +1,1 @@
-hello
+greetings
--- a/{b.as_posix()}
+++ b/{b.as_posix()}
@@ -1,1 +1,1 @@
-world
+earth
"""
    result = patch_apply(patch=patch)
    assert "across 2 file" in result
    assert a.read_text() == "greetings\n"
    assert b.read_text() == "earth\n"


def test_multi_file_rollback_on_partial_failure(tmp_path: Path) -> None:
    """First file's hunk applies; second file's hunk has a context
    mismatch. The whole operation should fail and BOTH files
    should be unchanged on disk."""
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("hello\n")
    b.write_text("DIFFERENT\n")  # doesn't match the patch's context

    patch = f"""--- a/{a.as_posix()}
+++ b/{a.as_posix()}
@@ -1,1 +1,1 @@
-hello
+goodbye
--- a/{b.as_posix()}
+++ b/{b.as_posix()}
@@ -1,1 +1,1 @@
-expected
+anything
"""
    result = patch_apply(patch=patch)
    assert result.startswith("ERROR:")
    # Both files unchanged.
    assert a.read_text() == "hello\n"
    assert b.read_text() == "DIFFERENT\n"


def test_nonexistent_file_returns_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.txt"
    patch = f"""--- a/{missing.as_posix()}
+++ b/{missing.as_posix()}
@@ -1,1 +1,1 @@
-x
+y
"""
    result = patch_apply(patch=patch)
    assert result.startswith("ERROR:")
    assert "does not exist" in result


def test_empty_patch_returns_error() -> None:
    assert patch_apply(patch="").startswith("ERROR:")
    assert patch_apply(patch="   \n").startswith("ERROR:")


def test_malformed_patch_returns_error(tmp_path: Path) -> None:
    result = patch_apply(patch="this is not a diff")
    assert result.startswith("ERROR:")
