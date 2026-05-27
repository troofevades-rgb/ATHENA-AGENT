"""Search tools — glob and ripgrep-style content search.

Falls back to pure Python if `rg` isn't on PATH.

Both Glob and the Python fallback for Grep walk the filesystem with
:func:`_safe_walk`, an ``os.walk``-based iterator that skips
directories which raise ``OSError`` on enumeration. This matters on
Windows where filenames containing Cyrillic / other non-ASCII bytes
can round-trip through pathlib's enumeration but fail when scandir
tries to descend into them — without the skip, a single bad
subdirectory anywhere under the workspace makes every search crash.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

from . import file_ops
from .registry import tool

_HAS_RG = shutil.which("rg") is not None


def _safe_walk(root: Path) -> Iterator[Path]:
    """Yield every file Path under ``root``, skipping directories that
    can't be scanned (encoding-mangled filenames, permission denied,
    broken symlinks). Per-entry failures are swallowed silently so one
    bad node doesn't tank the whole search.
    """
    # os.walk's onerror is called once per failing scandir — we want to
    # swallow them all, not propagate.
    def _skip(_err: OSError) -> None:
        return None

    for dirpath, _dirnames, filenames in os.walk(root, onerror=_skip):
        for fn in filenames:
            try:
                yield Path(dirpath) / fn
            except (OSError, ValueError):
                continue


def _glob_to_regex(pat: str) -> str:
    """Translate a glob pattern to a regex anchored on both ends.

    Hand-rolled because ``fnmatch.translate``'s wrapper format
    varies across Python versions and uses ``.*`` (which matches
    ``/``) for ``*`` — we need ``*`` to stay segment-local.

    Supported syntax:
      *           any chars except ``/``
      ?           single char except ``/``
      [abc]       char class (passed through verbatim)
      **/         any number of path segments (including zero)
      **          any chars including ``/`` (rare; usually written ``**/``)
      everything else is escaped literally
    """
    out: list[str] = []
    i = 0
    n = len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            if i + 1 < n and pat[i + 1] == "*":
                # ** — recursive across path separators
                i += 2
                if i < n and pat[i] == "/":
                    i += 1
                    # ``**/`` = zero or more segments, each ending in /
                    out.append(r"(?:.*/)?")
                else:
                    out.append(r".*")
            else:
                # single * — segment-local
                out.append(r"[^/]*")
                i += 1
        elif c == "?":
            out.append(r"[^/]")
            i += 1
        elif c == "[":
            j = pat.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
                i += 1
            else:
                out.append(pat[i : j + 1])
                i = j + 1
        elif c == "/":
            out.append("/")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return "^" + "".join(out) + "$"


def _match_glob_pattern(rel_path: str, pattern: str) -> bool:
    """Match a relative path string against a glob pattern.

    See :func:`_glob_to_regex` for the supported syntax. Empty
    patterns return False rather than matching everything (avoids
    surprise behaviour when callers pass ``glob=""``).
    """
    if not pattern:
        return False
    rp = rel_path.replace("\\", "/")
    pat = pattern.replace("\\", "/")
    try:
        return bool(re.match(_glob_to_regex(pat), rp))
    except re.error:
        return False


@tool(
    name="Glob",
    toolset="file",
    aliases=["glob"],
    description=(
        "Find files by glob pattern (e.g. '**/*.py', 'src/**/test_*.ts'). "
        "Returns paths relative to the workspace, sorted by modification time "
        "descending. Cross-OS — works the same on Windows, macOS, Linux. "
        "Use this INSTEAD OF `find` or `ls` in Bash for locating files by name."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "max_results": {"type": "integer", "description": "Default 200."},
        },
        "required": ["pattern"],
    },
)
def Glob(pattern: str, max_results: int = 200) -> str:
    root = file_ops._WORKSPACE
    matches: list[tuple[float, Path]] = []
    for p in _safe_walk(root):
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if not _match_glob_pattern(rel, pattern):
            continue
        try:
            matches.append((p.stat().st_mtime, p))
        except OSError:
            continue
    matches.sort(key=lambda t: t[0], reverse=True)
    matches = matches[: max(1, int(max_results))]
    if not matches:
        return "(no matches)"
    return "\n".join(p.relative_to(root).as_posix() for _, p in matches)


@tool(
    name="Grep",
    toolset="file",
    aliases=["grep"],
    description=(
        "Search file contents for a regex. Uses ripgrep when available, "
        "falls back to pure Python. Returns matches as file:line:content. "
        "Cross-OS — works the same on Windows, macOS, Linux, with no "
        "dependency on a `grep` binary being installed. "
        "Use this INSTEAD OF `grep`/`rg` in Bash for finding symbols, "
        "callers, references, or any text match across the codebase."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern"},
            "path": {
                "type": "string",
                "description": "Subdirectory or file to search (default: workspace root)",
            },
            "glob": {"type": "string", "description": "Optional file glob filter, e.g. '*.py'"},
            "max_results": {"type": "integer", "description": "Default 100."},
        },
        "required": ["pattern"],
    },
)
def Grep(
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    max_results: int = 100,
) -> str:
    root = file_ops._WORKSPACE
    target = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    max_results = max(1, int(max_results))
    if _HAS_RG:
        cmd = ["rg", "--no-heading", "--line-number", "--color", "never", "-m", str(max_results)]
        if glob:
            cmd += ["-g", glob]
        cmd += [pattern, str(target)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return "ERROR: grep timed out"
        if proc.returncode not in (0, 1):
            return f"ERROR: rg exited {proc.returncode}: {proc.stderr.strip()}"
        return proc.stdout.strip() or "(no matches)"
    # Python fallback
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"ERROR: bad regex: {e}"
    results: list[str] = []
    files: list[Path] = []
    if target.is_file():
        files = [target]
    elif glob:
        # Filter by the caller's glob (e.g. "*.py", "src/**/*.ts").
        files = [
            p for p in _safe_walk(target)
            if _match_glob_pattern(p.relative_to(target).as_posix(), glob)
        ]
    else:
        # No glob filter — match every file _safe_walk yields.
        files = list(_safe_walk(target))
    for f in files:
        try:
            for i, line in enumerate(
                f.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if rx.search(line):
                    results.append(f"{f.relative_to(root)}:{i}:{line}")
                    if len(results) >= max_results:
                        return "\n".join(results)
        except OSError:
            continue
    return "\n".join(results) if results else "(no matches)"
