"""The system-prompt Environment block now includes an OS-aware "tool
preference" nudge that steers the model toward first-class tools
(Grep, Glob, Read, Edit, Write, workspace_info) over shelling out.

The model is trained on millions of Linux examples and will reach for
`grep` on Windows out of habit unless the prompt is loud about
preferring the tool layer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.prompts.system import EnvironmentInfo


def _env(platform: str, **overrides) -> EnvironmentInfo:
    base = dict(
        cwd=Path("/tmp"),
        is_git=False,
        platform=platform,
        os_version="x",
        shell="/bin/bash",
        model="test-model",
        today="2026-05-21",
        hostname="h",
        user="u",
    )
    base.update(overrides)
    return EnvironmentInfo(**base)


def test_render_includes_tool_preference_line():
    out = _env("linux").render()
    assert "Tool preference" in out


def test_render_pushes_first_class_tools():
    out = _env("linux").render()
    # All five first-class tools should be name-dropped.
    for name in ("Grep", "Glob", "Read", "Edit", "Write", "workspace_info"):
        assert name in out, f"{name} missing from tool-preference block"


def test_render_pushes_against_shelling_out():
    out = _env("linux").render()
    assert "first-class tools" in out.lower()
    assert "bash only for" in out.lower()


def test_windows_block_mentions_git_bash():
    """Windows-specific hint: Bash is Git Bash / MSYS — POSIX utilities
    may be limited. The model should know not to assume `grep` exists."""
    out = _env("win32").render()
    assert "git bash" in out.lower() or "msys" in out.lower()
    assert "posix utilities may be limited" in out.lower()


def test_darwin_block_mentions_bsd_userland():
    """macOS has BSD userland — `grep`/`sed` flags differ from GNU."""
    out = _env("darwin").render()
    assert "bsd" in out.lower()


def test_linux_block_mentions_gnu_userland():
    out = _env("linux").render()
    assert "gnu userland" in out.lower()


def test_unknown_platform_falls_through_to_linux_style():
    """Unknown platforms (freebsd, sunos, etc.) get the GNU branch as
    the least-surprising default — better than no preference block."""
    out = _env("freebsd").render()
    assert "Tool preference" in out
    # Must still nudge toward first-class tools regardless of platform.
    assert "Grep" in out
