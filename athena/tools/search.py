"""Search tools — glob and ripgrep-style content search.

Falls back to pure Python if `rg` isn't on PATH.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from . import file_ops
from .registry import tool

_HAS_RG = shutil.which("rg") is not None


@tool(
    name="Glob",
    toolset="file",
    aliases=["glob"],
    description=(
        "Find files by glob pattern (e.g. '**/*.py', 'src/**/test_*.ts'). "
        "Returns paths relative to the workspace, sorted by modification time "
        "descending. Use this when you need to locate files by name pattern."
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
    matches = []
    for p in root.glob(pattern):
        if p.is_file():
            try:
                matches.append((p.stat().st_mtime, p))
            except OSError:
                pass
    matches.sort(key=lambda t: t[0], reverse=True)
    matches = matches[: max(1, int(max_results))]
    if not matches:
        return "(no matches)"
    return "\n".join(str(p.relative_to(root)) for _, p in matches)


@tool(
    name="Grep",
    toolset="file",
    aliases=["grep"],
    description=(
        "Search file contents for a regex. Uses ripgrep when available, "
        "falls back to Python. Returns matches as file:line:content. "
        "Use this for finding symbols, callers, references, or any text "
        "match across the codebase."
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
    else:
        files = [p for p in target.rglob(glob or "*") if p.is_file()]
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
