#!/usr/bin/env python3
"""Cut a release: bump the version in lockstep and roll the CHANGELOG.

athena ships to PyPI on a ``v*`` tag push (see docs/release.md). Two
footguns make hand-cut releases fragile, and this script removes both:

  1. The version lives in TWO places — ``pyproject.toml`` ([project]
     ``version``) and ``athena/__init__.py`` (``__version__``). The
     version-sync CI gate (scripts/verify_version.py) fails the build
     when they drift, and ``python -m build`` reads the version from
     pyproject — NOT from the git tag — so tagging ``v0.4.1`` while
     pyproject still says ``0.4.0`` silently republishes 0.4.0 (which
     then no-ops on ``skip-existing``) instead of shipping 0.4.1.
  2. The CHANGELOG's ``## [Unreleased]`` block has to be promoted to a
     dated, versioned section by hand.

This script does both atomically, refuses to go backwards, self-checks
that version-sync will pass, and prints the exact commit + tag commands.
It never runs git itself — bump, review ``git diff``, land via PR
(master is protected), then tag.

Usage::

    python scripts/release.py 0.4.1
    python scripts/release.py 0.5.0rc1 --dry-run
    python scripts/release.py 1.0.0 --date 2026-07-01
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
INIT = REPO_ROOT / "athena" / "__init__.py"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

# Column-0 `version = "..."` (the [project] one). Anchored to line start
# so it can never match ruff's `target-version` or an indented dep pin.
PYPROJECT_VERSION_RE = re.compile(r'^version = "([^"]+)"', re.MULTILINE)
INIT_VERSION_RE = re.compile(r'^__version__ = "([^"]+)"', re.MULTILINE)

# X.Y.Z with at most one pre-release segment (aN / bN / rcN / devN); the
# separator may be -, _, ., or nothing. Normalized to PEP 440 on the way
# out (no separator before a/b/rc; ".devN" for dev).
VERSION_RE = re.compile(
    r"^(?P<maj>\d+)\.(?P<min>\d+)\.(?P<pat>\d+)"
    r"(?:[-_.]?(?P<pre>a|b|rc)(?P<pren>\d+))?"
    r"(?:[-_.]?dev(?P<devn>\d+))?$"
)

# PEP 440 ordering of the pre-release stage. A final release outranks
# every pre-release stage, so it sits highest.
_PRE_RANK = {"dev": 0, "a": 1, "b": 2, "rc": 3, None: 4}


class ReleaseError(Exception):
    """A user-facing failure — printed without a traceback."""


def parse_version(raw: str) -> tuple[str, tuple[int, ...], bool]:
    """Return ``(normalized, sort_key, is_prerelease)`` or raise.

    ``sort_key`` is comparable across versions for the downgrade guard.
    ``is_prerelease`` drives the TestPyPI-vs-PyPI hint at the end.
    """
    m = VERSION_RE.match(raw.strip())
    if not m:
        raise ReleaseError(
            f"{raw!r} is not an accepted version. Expected X.Y.Z with an "
            "optional pre-release (e.g. 0.4.1, 0.5.0rc1, 1.0.0b2, 1.0.0.dev3)."
        )
    pre, devn = m.group("pre"), m.group("devn")
    if pre is not None and devn is not None:
        raise ReleaseError(f"{raw!r} mixes a pre-release and a dev segment; pick one.")
    maj, mn, pat = int(m["maj"]), int(m["min"]), int(m["pat"])

    base = f"{maj}.{mn}.{pat}"
    if pre is not None:
        normalized = f"{base}{pre}{int(m['pren'])}"
        rank, num = _PRE_RANK[pre], int(m["pren"])
        is_pre = True
    elif devn is not None:
        normalized = f"{base}.dev{int(devn)}"
        rank, num = _PRE_RANK["dev"], int(devn)
        is_pre = True
    else:
        normalized = base
        rank, num = _PRE_RANK[None], 0
        is_pre = False

    return normalized, (maj, mn, pat, rank, num), is_pre


def _read(path: Path) -> str:
    if not path.exists():
        raise ReleaseError(f"missing expected file: {path}")
    return path.read_text(encoding="utf-8")


def _swap_version(text: str, regex: re.Pattern[str], new: str, where: str) -> tuple[str, str]:
    """Replace only the captured version span; return ``(new_text, old)``."""
    m = regex.search(text)
    if not m:
        raise ReleaseError(f"could not find a version line in {where}")
    old = m.group(1)
    new_text = text[: m.start(1)] + new + text[m.end(1) :]
    return new_text, old


def roll_changelog(text: str, version: str, date: str) -> tuple[str, bool]:
    """Promote the ``## [Unreleased]`` block into a dated section.

    Returns ``(new_text, had_entries)``. A fresh empty ``[Unreleased]``
    is left at the top; whatever sat under it moves down verbatim.
    """
    m = re.search(r"(?m)^## \[Unreleased\][^\n]*\n", text)
    if not m:
        raise ReleaseError("CHANGELOG.md has no '## [Unreleased]' heading")
    body_start = m.end()
    nxt = re.search(r"(?m)^## \[", text[body_start:])
    body_end = body_start + nxt.start() if nxt else len(text)
    body = text[body_start:body_end].strip("\n")

    dated = f"## [{version}] - {date}\n"
    if body:
        dated += "\n" + body + "\n\n"
    else:
        dated += "\n"
    rebuilt = "## [Unreleased]\n\n" + dated
    new_text = text[: m.start()] + rebuilt + text[body_end:]
    return new_text, bool(body)


def _diff(old: str, new: str, path: Path) -> str:
    rel = path.relative_to(REPO_ROOT).as_posix()
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
    )
    return "".join(lines).rstrip("\n")


def _force_utf8_streams() -> None:
    """Make stdout/stderr UTF-8.

    The CHANGELOG legitimately contains non-ASCII (em dashes, arrows),
    so the unified diff we print does too. On Windows the console
    defaults to cp1252 and a bare ``print`` of that text raises
    ``UnicodeEncodeError`` — which is exactly where this script runs.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        description="Bump version in lockstep + roll the CHANGELOG for a release.",
    )
    parser.add_argument("version", help="new version, e.g. 0.4.1 or 0.5.0rc1")
    parser.add_argument(
        "--date",
        default=datetime.date.today().isoformat(),
        help="release date for the CHANGELOG heading (default: today, YYYY-MM-DD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the diffs without writing anything",
    )
    parser.add_argument(
        "--no-changelog",
        action="store_true",
        help="bump versions only; leave CHANGELOG.md untouched",
    )
    parser.add_argument(
        "--allow-downgrade",
        action="store_true",
        help="permit a version lower than the current one (rarely correct)",
    )
    args = parser.parse_args(argv)

    try:
        new_version, new_key, is_pre = parse_version(args.version)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
            raise ReleaseError(f"--date {args.date!r} is not YYYY-MM-DD")

        pyproject_text = _read(PYPROJECT)
        init_text = _read(INIT)

        new_pyproject, old_pyproject = _swap_version(
            pyproject_text, PYPROJECT_VERSION_RE, new_version, "pyproject.toml"
        )
        new_init, old_init = _swap_version(
            init_text, INIT_VERSION_RE, new_version, "athena/__init__.py"
        )

        if old_pyproject != old_init:
            print(
                f"warning: pyproject ({old_pyproject}) and __version__ ({old_init}) "
                "already disagree; this release re-syncs both.",
                file=sys.stderr,
            )

        _, cur_key, _ = parse_version(old_pyproject)
        if new_key <= cur_key and not args.allow_downgrade:
            rel = "the same as" if new_key == cur_key else "lower than"
            raise ReleaseError(
                f"{new_version} is {rel} the current version {old_pyproject}. "
                "PyPI never lets a version be re-uploaded - bump higher "
                "(or pass --allow-downgrade if you truly mean it)."
            )

        edits: list[tuple[Path, str, str]] = [
            (PYPROJECT, pyproject_text, new_pyproject),
            (INIT, init_text, new_init),
        ]
        had_entries = True
        if not args.no_changelog:
            changelog_text = _read(CHANGELOG)
            new_changelog, had_entries = roll_changelog(changelog_text, new_version, args.date)
            edits.append((CHANGELOG, changelog_text, new_changelog))

        if args.dry_run:
            for path, old, new in edits:
                print(_diff(old, new, path))
                print()
            print(f"(dry run — no files written; would release {new_version})")
            return 0

        for path, _old, new in edits:
            path.write_text(new, encoding="utf-8")

        # Self-check: both surfaces now agree, so version-sync will pass.
        check_pyproject = PYPROJECT_VERSION_RE.search(_read(PYPROJECT))
        check_init = INIT_VERSION_RE.search(_read(INIT))
        got_py = check_pyproject.group(1) if check_pyproject else None
        got_init = check_init.group(1) if check_init else None
        if got_py != new_version or got_init != new_version:
            raise ReleaseError(
                "post-write self-check failed: "
                f"pyproject={got_py!r} __version__={got_init!r} expected={new_version!r}. "
                "Files may be partially edited — inspect 'git diff' before committing."
            )

        _print_summary(new_version, args.date, is_pre, had_entries, args.no_changelog)
        return 0

    except ReleaseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _print_summary(
    version: str, date: str, is_pre: bool, had_entries: bool, no_changelog: bool
) -> None:
    print(f"Bumped to {version} (pyproject.toml + athena/__init__.py).")
    if no_changelog:
        print("CHANGELOG.md left untouched (--no-changelog).")
    elif had_entries:
        print(f"CHANGELOG: promoted [Unreleased] -> [{version}] - {date}.")
    else:
        print(
            f"CHANGELOG: created an EMPTY [{version}] section — "
            "[Unreleased] had no entries. Add release notes before tagging."
        )
    print()
    print("Next steps:")
    print("  1. Review:  git diff")
    print("  2. Land the bump (master is protected, so via PR):")
    print(f"       git switch -c release/{version}")
    print(f'       git commit -am "release: {version}"')
    print(f"       git push -u origin release/{version}")
    print("       gh pr create --base master --fill")
    print("  3. After it merges, tag the merge commit and push:")
    print("       git switch master && git pull")
    print(f"       git tag v{version} && git push origin v{version}")
    print()
    if is_pre:
        print(
            f"  v{version} is a PRE-RELEASE -> the publish workflow targets "
            "TestPyPI (stable tags go to real PyPI). See docs/release.md."
        )
    else:
        print(
            f"  v{version} is a stable tag -> the publish workflow ships it "
            "to real PyPI. See docs/release.md."
        )


if __name__ == "__main__":
    raise SystemExit(main())
