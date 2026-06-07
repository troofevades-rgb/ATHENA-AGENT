"""Regression guard: no contributor's personal paths in tracked files.

A public repo must not leak a contributor's username or home-directory
layout. It happened once — via committed pytest output and manual
runbooks — which is why those were scrubbed and moved local-only
(gitignored). This test fails if the known personal username reappears
in any *git-tracked* file, so the next accidental paste is caught here
instead of in review (or after publish).

Local-only artifacts (test plans, runbooks, recon notes) are gitignored
and therefore not tracked, so they're correctly out of scope — they may
legitimately contain absolute local paths.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Assembled from fragments at runtime so this guard file does not match
# itself when it scans the tree. Add more usernames here if other
# contributors' paths ever leak.
_FORBIDDEN: tuple[str, ...] = ("mtt" "_j",)


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "ls-files", "-z"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git not available")
    return [_REPO_ROOT / p for p in out.split("\0") if p]


def test_no_personal_paths_in_tracked_files() -> None:
    offenders: list[str] = []
    for path in _tracked_files():
        if "node_modules" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, IsADirectoryError):
            continue
        for needle in _FORBIDDEN:
            if needle in text:
                offenders.append(f"{path.relative_to(_REPO_ROOT)} contains {needle!r}")
    assert not offenders, (
        "Personal paths leaked into tracked files — scrub them or make the "
        "file local-only (gitignore it):\n  " + "\n  ".join(offenders)
    )
