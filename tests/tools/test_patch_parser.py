"""Tests for athena.tools.patch_parser (T2-07.2)."""

from __future__ import annotations

import pytest

from athena.tools.patch_parser import (
    PatchParseError,
    apply_patch_to_text,
    parse_patch,
)

# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def test_parse_single_file_single_hunk() -> None:
    text = """--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 line1
-line2
+line2_changed
 line3
"""
    patch = parse_patch(text)
    assert len(patch.files) == 1
    assert patch.files[0].old_path == "foo.py"
    assert patch.files[0].new_path == "foo.py"
    assert len(patch.files[0].hunks) == 1
    hunk = patch.files[0].hunks[0]
    assert hunk.old_start == 1
    assert hunk.old_count == 3
    assert hunk.new_count == 3


def test_parse_multi_hunk() -> None:
    text = """--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 a
-b
+B
 c
@@ -10,2 +10,2 @@
 d
-e
+E
"""
    patch = parse_patch(text)
    assert len(patch.files[0].hunks) == 2


def test_parse_multi_file() -> None:
    text = """--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,1 @@
-old
+new
--- a/bar.py
+++ b/bar.py
@@ -1,1 +1,1 @@
-old
+new
"""
    patch = parse_patch(text)
    assert len(patch.files) == 2
    assert {f.old_path for f in patch.files} == {"foo.py", "bar.py"}


def test_parse_rejects_missing_plus_header() -> None:
    text = "--- a/foo.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"
    with pytest.raises(PatchParseError):
        parse_patch(text)


def test_parse_tolerates_leading_garbage() -> None:
    """A commit message / signed-off-by line before the first --- is OK."""
    text = """commit abcdef
Author: Someone <s@example.com>
Date: today

Some subject

--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,1 @@
-old
+new
"""
    patch = parse_patch(text)
    assert len(patch.files) == 1


def test_parse_hunk_without_count_defaults_to_one() -> None:
    """``@@ -1 +1 @@`` (no comma+count) means count==1."""
    text = """--- a/x
+++ b/x
@@ -1 +1 @@
-old
+new
"""
    patch = parse_patch(text)
    hunk = patch.files[0].hunks[0]
    assert hunk.old_count == 1
    assert hunk.new_count == 1


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def test_apply_basic() -> None:
    original = "line1\nline2\nline3\n"
    patch_text = """--- a/x
+++ b/x
@@ -1,3 +1,3 @@
 line1
-line2
+line2_changed
 line3
"""
    patch = parse_patch(patch_text)
    result = apply_patch_to_text(original, patch.files[0])
    assert result == "line1\nline2_changed\nline3\n"


def test_apply_context_mismatch_raises() -> None:
    original = "line1\nDIFFERENT\nline3\n"
    patch_text = """--- a/x
+++ b/x
@@ -1,3 +1,3 @@
 line1
-line2
+line2_changed
 line3
"""
    patch = parse_patch(patch_text)
    with pytest.raises(PatchParseError):
        apply_patch_to_text(original, patch.files[0])


def test_apply_multi_hunk() -> None:
    original = "a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n"
    patch_text = """--- a/x
+++ b/x
@@ -2,1 +2,1 @@
-b
+B
@@ -8,1 +8,1 @@
-h
+H
"""
    patch = parse_patch(patch_text)
    result = apply_patch_to_text(original, patch.files[0])
    assert "B" in result and "H" in result
    # Verify ordering preserved.
    new_lines = result.splitlines()
    assert new_lines[1] == "B"
    assert new_lines[7] == "H"


def test_apply_pure_insertion() -> None:
    original = "a\nb\nc\n"
    patch_text = """--- a/x
+++ b/x
@@ -2,1 +2,2 @@
 b
+new_line
"""
    patch = parse_patch(patch_text)
    result = apply_patch_to_text(original, patch.files[0])
    assert result == "a\nb\nnew_line\nc\n"


def test_apply_pure_deletion() -> None:
    original = "a\nb\nc\n"
    patch_text = """--- a/x
+++ b/x
@@ -2,1 +2,0 @@
-b
"""
    patch = parse_patch(patch_text)
    result = apply_patch_to_text(original, patch.files[0])
    assert result == "a\nc\n"
