"""File read / write / surgical edit tools.

Tool names follow Claude Code conventions: Read, Write, Edit. Old snake_case
names (read_file, write_file, str_replace) remain as aliases so legacy
ATHENA.md (or pre-rename OCODE.md) instructions and saved sessions keep
working.
"""

from __future__ import annotations

from pathlib import Path

from .delta_lint import lint_after_write
from .registry import tool

# Set by agent at startup so all paths are resolved relative to the project root.
_WORKSPACE: Path = Path.cwd()
_MAX_READ = 256_000


def set_workspace(path: Path, max_read: int = 256_000) -> None:
    global _WORKSPACE, _MAX_READ
    _WORKSPACE = path.resolve()
    _MAX_READ = max_read


def _resolve(path: str) -> Path:
    """Resolve a possibly-relative path against the workspace.

    We don't hard-block out-of-workspace reads (the user may legitimately
    want to view /etc/something), but we WILL block writes outside the
    workspace.
    """
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = _WORKSPACE / p
    return p.resolve()


def _within_workspace(p: Path) -> bool:
    try:
        p.resolve().relative_to(_WORKSPACE)
        return True
    except ValueError:
        return False


# ---- Read ---------------------------------------------------------------


@tool(
    name="Read",
    toolset="file",
    aliases=["read_file"],
    description=(
        "Read a file from the local filesystem. Returns numbered lines so "
        "you can reference exact line ranges in subsequent edits. "
        "Use this before editing any file. Supports offset/limit for paging "
        "through large files."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute or workspace-relative path."},
            "offset": {"type": "integer", "description": "1-indexed line number to start at."},
            "limit": {"type": "integer", "description": "Number of lines to read."},
        },
        "required": ["file_path"],
    },
)
def Read(file_path: str, offset: int | None = None, limit: int | None = None, **legacy) -> str:
    # Back-compat: also accept path / start_line / end_line from old call sites.
    file_path = file_path or legacy.get("path")  # type: ignore[assignment]
    if offset is None and "start_line" in legacy:
        offset = legacy["start_line"]
    if limit is None and "end_line" in legacy:
        end = legacy["end_line"]
        if end and end != -1 and offset:
            limit = max(0, end - offset + 1)

    p = _resolve(file_path)
    if not p.exists():
        return f"ERROR: file not found: {p}"
    if p.is_dir():
        return f"ERROR: {p} is a directory; use Glob or Bash `ls`."
    try:
        data = p.read_bytes()
    except OSError as e:
        return f"ERROR reading {p}: {e}"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return f"ERROR: {p} appears to be binary."
    # Apply offset/limit to the FULL line set so pagination reaches deep into
    # large files. The byte cap below applies to the formatted output.
    lines = text.splitlines()
    start = max(0, (offset or 1) - 1)
    end = min(len(lines), start + (limit if limit else len(lines)))
    width = max(len(str(end)), 1)
    out = "\n".join(f"{i + 1:>{width}}\t{lines[i]}" for i in range(start, end))
    truncated = ""
    if len(out) > _MAX_READ:
        out = out[:_MAX_READ]
        truncated = (
            f"\n... [output truncated at {_MAX_READ} bytes; "
            "pass a smaller `limit` or use `offset` to page] ..."
        )
    return out + truncated


# ---- Write --------------------------------------------------------------


@tool(
    name="Write",
    toolset="file",
    aliases=["write_file"],
    description=(
        "Write a file to the local filesystem. Overwrites if it exists. "
        "For surgical edits to existing files, prefer Edit. NEVER create "
        "documentation files (*.md, README) unless explicitly requested."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["file_path", "content"],
    },
    requires_confirmation=True,
)
def Write(file_path: str = "", content: str = "", **legacy) -> str:
    file_path = file_path or legacy.get("path", "")
    p = _resolve(file_path)
    if not _within_workspace(p):
        return f"ERROR: refusing to write outside workspace: {p}"
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    p.write_text(content, encoding="utf-8")
    lint_err = lint_after_write(p, content)
    if lint_err:
        return (
            f"{'overwrote' if existed else 'created'} {p} ({len(content)} bytes) "
            f"but failed validation: {lint_err}. "
            "Fix the syntax and re-call Write."
        )
    return f"{'overwrote' if existed else 'created'} {p} ({len(content)} bytes)"


# ---- Edit (str_replace) -------------------------------------------------


@tool(
    name="Edit",
    toolset="file",
    aliases=["str_replace"],
    description=(
        "Performs exact string replacement in a file. `old_string` must "
        "match the file content verbatim. By default `old_string` must be "
        "unique; pass replace_all=true to replace every occurrence. "
        "ALWAYS Read the file first so old_string is exact."
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "old_string": {"type": "string", "description": "Exact text to find."},
            "new_string": {
                "type": "string",
                "description": "Replacement text. Empty string deletes.",
            },
            "replace_all": {"type": "boolean", "description": "Default false."},
        },
        "required": ["file_path", "old_string", "new_string"],
    },
    requires_confirmation=True,
)
def Edit(
    file_path: str = "",
    old_string: str = "",
    new_string: str = "",
    replace_all: bool = False,
    **legacy,
) -> str:
    # Back-compat: old call sites used path/old_str/new_str
    file_path = file_path or legacy.get("path", "")
    old_string = old_string or legacy.get("old_str", "")
    new_string = new_string or legacy.get("new_str", "")

    p = _resolve(file_path)
    if not _within_workspace(p):
        return f"ERROR: refusing to write outside workspace: {p}"
    if not p.exists():
        return f"ERROR: file not found: {p}"
    text = p.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        return f"ERROR: old_string not found in {p}. Re-read the file and copy text exactly."
    if count > 1 and not replace_all:
        return (
            f"ERROR: old_string matches {count} times in {p}. "
            "Add surrounding context to make it unique, or pass replace_all=true."
        )
    if replace_all:
        new_text = text.replace(old_string, new_string)
        replacements = count
    else:
        new_text = text.replace(old_string, new_string, 1)
        replacements = 1
    p.write_text(new_text, encoding="utf-8")
    lint_err = lint_after_write(p, new_text)
    if lint_err:
        return (
            f"edited {p}: replaced {replacements} occurrence(s) "
            f"but failed validation: {lint_err}. "
            "Fix the syntax and re-call Edit."
        )
    return f"edited {p}: replaced {replacements} occurrence(s) ({len(old_string)} -> {len(new_string)} chars each)"


# ---- list_dir (kept for convenience; no Claude Code analogue) -----------


@tool(
    name="list_dir",
    toolset="file",
    description="List entries in a directory (one level). Files and dirs marked with trailing /.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path; defaults to workspace root.",
            },
        },
    },
)
def list_dir(path: str = ".") -> str:
    p = _resolve(path)
    if not p.exists():
        return f"ERROR: not found: {p}"
    if not p.is_dir():
        return f"ERROR: not a directory: {p}"
    entries = []
    for child in sorted(p.iterdir()):
        if child.name.startswith(".") and child.name not in (".env", ".gitignore"):
            continue
        suffix = "/" if child.is_dir() else ""
        try:
            size = child.stat().st_size if child.is_file() else 0
        except OSError:
            size = 0
        entries.append(f"{child.name}{suffix}\t{size}")
    return "\n".join(entries) if entries else "(empty)"
