"""Bash on Windows mangles backslash-separated drive paths.

``python C:\\Users\\foo\\bar.py`` becomes ``python C:Usersfoobar.py``
after Bash (Git Bash / MSYS) processes the backslash escapes. Detect
drive-letter paths in commands and rewrite to forward slashes before
exec. POSIX is a no-op.
"""

from __future__ import annotations

import pytest

from athena.tools.shell import _normalize_windows_paths


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr("athena.tools.shell._IS_WINDOWS", True)


@pytest.fixture
def on_posix(monkeypatch):
    monkeypatch.setattr("athena.tools.shell._IS_WINDOWS", False)


# ----------------------------------------------------------------------
# Drive-letter paths get rewritten
# ----------------------------------------------------------------------


def test_simple_path_normalized(on_windows):
    out = _normalize_windows_paths(r"python C:\Users\foo\bar.py")
    assert out == "python C:/Users/foo/bar.py"


def test_drive_letter_only(on_windows):
    """``cd C:\\`` should still be rewritten."""
    out = _normalize_windows_paths(r"cd C:\Users\foo")
    assert out == "cd C:/Users/foo"


def test_lowercase_drive_letter(on_windows):
    out = _normalize_windows_paths(r"python d:\projects\hello.py")
    assert out == "python d:/projects/hello.py"


def test_multiple_paths_in_one_command(on_windows):
    out = _normalize_windows_paths(r"cp C:\src\file.txt D:\dst\file.txt")
    assert out == "cp C:/src/file.txt D:/dst/file.txt"


def test_path_with_chained_commands(on_windows):
    """The transcript pattern: model uses && to chain. Drive paths in
    each segment should both get fixed."""
    out = _normalize_windows_paths(r"cd C:\Users\foo && python C:\Users\foo\bar.py")
    assert out == "cd C:/Users/foo && python C:/Users/foo/bar.py"


def test_quoted_path_also_rewritten(on_windows):
    """Quoted paths get the same treatment — the quote characters
    aren't valid drive-letter prefixes, so the regex starts AT the
    drive letter and stops at the next shell metacharacter."""
    out = _normalize_windows_paths(r'python "C:\Users\foo\bar.py"')
    assert out == 'python "C:/Users/foo/bar.py"'


# ----------------------------------------------------------------------
# Non-path backslashes are preserved
# ----------------------------------------------------------------------


def test_regex_backslashes_preserved(on_windows):
    """A grep pattern with ``\\d+`` mustn't be touched."""
    out = _normalize_windows_paths(r'grep -E "\d+" file.txt')
    assert out == r'grep -E "\d+" file.txt'


def test_echo_with_escape_preserved(on_windows):
    """Shell-side escape sequences (no drive letter) stay verbatim."""
    out = _normalize_windows_paths(r'echo "line1\nline2"')
    assert out == r'echo "line1\nline2"'


def test_no_paths_in_command(on_windows):
    out = _normalize_windows_paths("ls -la && pwd")
    assert out == "ls -la && pwd"


def test_forward_slash_path_unchanged(on_windows):
    """Already-correct forward-slash paths get no second rewrite."""
    out = _normalize_windows_paths("python C:/Users/foo/bar.py")
    assert out == "python C:/Users/foo/bar.py"


# ----------------------------------------------------------------------
# POSIX no-op
# ----------------------------------------------------------------------


def test_posix_is_noop(on_posix):
    """On Linux/macOS, ``C:\\`` could legitimately appear as a literal
    string (e.g. testing Windows-path handling). Never rewrite."""
    cmd = r"echo 'C:\Users\foo'"
    assert _normalize_windows_paths(cmd) == cmd


# ----------------------------------------------------------------------
# Integration: Bash tool description carries the warning
# ----------------------------------------------------------------------


def test_bash_description_warns_about_backslashes():
    """The model's only line of defense before the auto-fix is the
    tool description. It MUST tell the model to use forward slashes
    on Windows."""
    import athena.tools  # noqa: F401 — populates registry
    from athena.tools.registry import get_tool

    bash = get_tool("Bash")
    assert bash is not None
    desc = bash.description.lower()
    assert "windows paths" in desc
    assert "forward slashes" in desc
    # Either an explicit example or the underlying explanation.
    assert "backslash" in desc or "escape" in desc


# ----------------------------------------------------------------------
# Integration: the regression case from the transcript
# ----------------------------------------------------------------------


def test_exact_regression_from_transcript(on_windows):
    """The literal command from the user's transcript — verify it
    would now reach python with a runnable path."""
    out = _normalize_windows_paths(r"python C:\Users\dev\projects\myproject\hello_world.py")
    assert out == "python C:/Users/dev/projects/myproject/hello_world.py"
