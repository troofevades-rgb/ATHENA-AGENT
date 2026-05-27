"""Tool-description tests — make sure Bash steers the model toward
first-class tools, and Grep/Glob advertise their cross-OS reliability.

If these strings drift, the model will reach for `grep` on Windows out
of habit. The descriptions are the only thing keeping it honest.
"""

from __future__ import annotations

import athena.tools  # noqa: F401 — populates registry
from athena.tools.registry import get_tool


def test_bash_description_lists_alternatives():
    """Every alternative the model should reach for first appears in the
    Bash description with its replacement."""
    bash = get_tool("Bash")
    assert bash is not None
    desc = bash.description.lower()

    # Each of the six first-class tool replacements MUST be named.
    for replacement in ("grep", "glob", "read", "edit", "write", "workspace_info"):
        assert replacement in desc, f"Bash desc missing {replacement!r}"

    # The "prefer first-class tools" framing must be present.
    assert "first-class tools" in desc


def test_bash_description_mentions_windows_concern():
    bash = get_tool("Bash")
    assert bash is not None
    desc = bash.description.lower()
    # Windows users hit this most — desc must call out the install gap.
    assert "windows" in desc


def test_grep_description_advertises_cross_os():
    grep = get_tool("Grep")
    assert grep is not None
    desc = grep.description.lower()
    assert "cross-os" in desc or "every os" in desc or "windows" in desc


def test_grep_description_steers_away_from_bash_grep():
    grep = get_tool("Grep")
    assert grep is not None
    desc = grep.description.lower()
    # Explicit "use this instead of grep in Bash"
    assert "instead of" in desc


def test_glob_description_advertises_cross_os():
    glob = get_tool("Glob")
    assert glob is not None
    desc = glob.description.lower()
    assert "cross-os" in desc or "every os" in desc


def test_glob_description_steers_away_from_find_ls():
    glob = get_tool("Glob")
    assert glob is not None
    desc = glob.description.lower()
    assert "find" in desc or "ls" in desc
    assert "instead of" in desc
