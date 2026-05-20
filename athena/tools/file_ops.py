"""File read / write / surgical edit tools.

Tool names follow Claude Code conventions: Read, Write, Edit. Old snake_case
names (read_file, write_file, str_replace) remain as aliases so legacy
ATHENA.md (or pre-rename OCODE.md) instructions and saved sessions keep
working.
"""

from __future__ import annotations

from pathlib import Path

from ..safety.path_security import set_workspace as _set_path_security_workspace
from ..safety.path_security import validate_path
from .delta_lint import lint_after_write
from .registry import tool

# Set by agent at startup so all paths are resolved relative to the project root.
_WORKSPACE: Path = Path.cwd()
_MAX_READ = 256_000


def set_workspace(path: Path, max_read: int = 256_000) -> None:
    """Set the workspace root for file_ops AND path_security."""
    global _WORKSPACE, _MAX_READ
    _WORKSPACE = path.resolve()
    _MAX_READ = max_read
    _set_path_security_workspace(_WORKSPACE)


def _verify_after_write(p: Path) -> str:
    """T5-04 post-write verification.

    Returns a one-line tail to append to the tool's return string,
    or an empty string when verification is off / silent-passing.
    A failed verification surfaces the rollback hint inline so the
    model sees it in the tool result.

    Best-effort: any exception inside the verifier becomes a debug
    log + empty suffix. The write itself is never blocked.
    """
    try:
        from ..config import load_config

        cfg = load_config()
        if getattr(cfg, "verify_on_write", "diagnose") == "off":
            return ""
        from ..verify import VerifiedExecution

        verifier = VerifiedExecution(cfg=cfg, workspace=_WORKSPACE)
        outcome = verifier.verify_write(p)
    except Exception:  # noqa: BLE001
        import logging as _logging

        _logging.getLogger(__name__).debug(
            "post-write verify failed for %s", p, exc_info=True
        )
        return ""
    # passed → quiet (no noise on the green path), failure / skipped
    # → surface the full report so the rollback hint reaches the
    # model.
    if outcome.outcome == "passed":
        return ""
    return "\n" + outcome.report()


def _resolve(path: str, *, intent: str) -> Path:
    """Resolve a possibly-relative path against the workspace, then
    validate it via path_security.

    Inside-workspace paths pass through unconditionally. Outside-workspace
    paths route through the active approval callback (forks see AUTO_DENY).
    Absolute-deny paths (process memory, kernel memory, raw devices) are
    refused regardless of approval.
    """
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = _WORKSPACE / p
    return validate_path(p, intent=intent)  # type: ignore[arg-type]


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

    p = _resolve(file_path, intent="read")
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
    p = _resolve(file_path, intent="write")
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    p.write_text(content, encoding="utf-8")
    from ..agent.checkpoints import track_modified_file as _track

    _track(p)
    lint_err = lint_after_write(p, content)
    if lint_err:
        return (
            f"{'overwrote' if existed else 'created'} {p} ({len(content)} bytes) "
            f"but failed validation: {lint_err}. "
            "Fix the syntax and re-call Write."
        )
    verify_tail = _verify_after_write(p)
    return (
        f"{'overwrote' if existed else 'created'} {p} ({len(content)} bytes)"
        + verify_tail
    )


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
            "fuzzy": {
                "type": "boolean",
                "description": (
                    "If true, fall back to fuzzy substring matching when "
                    "old_string doesn't match verbatim. Requires EXACTLY ONE "
                    "near-match above the threshold; multiple matches error "
                    "out and ask the agent to include more disambiguating "
                    "context. Default false."
                ),
            },
            "fuzzy_threshold": {
                "type": "number",
                "description": (
                    "Similarity threshold in [0,1] for the fuzzy fallback (default 0.95)."
                ),
            },
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
    fuzzy: bool = False,
    fuzzy_threshold: float = 0.95,
    **legacy,
) -> str:
    # Back-compat: old call sites used path/old_str/new_str
    file_path = file_path or legacy.get("path", "")
    old_string = old_string or legacy.get("old_str", "")
    new_string = new_string or legacy.get("new_str", "")

    p = _resolve(file_path, intent="write")
    if not p.exists():
        return f"ERROR: file not found: {p}"
    text = p.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        # T2-07: optional fuzzy fallback. Returns ERROR rather than
        # speculating when 0 or >1 near-matches are above threshold;
        # callers are expected to retry with more context.
        if not fuzzy:
            return (
                f"ERROR: old_string not found in {p}. Re-read the file and "
                "copy text exactly, or pass fuzzy=true to enable approximate "
                "matching."
            )
        from .fuzzy_match import find_fuzzy_matches

        matches = find_fuzzy_matches(text, old_string, threshold=fuzzy_threshold)
        if not matches:
            return (
                f"ERROR: no fuzzy match for old_string in {p} above "
                f"threshold={fuzzy_threshold}. Provide more accurate context."
            )
        if len(matches) > 1:
            return (
                f"ERROR: {len(matches)} fuzzy matches above threshold="
                f"{fuzzy_threshold} in {p}. Include more surrounding "
                "context in old_string to disambiguate."
            )
        match = matches[0]
        new_text = text[: match.start] + new_string + text[match.end :]
        replacements = 1
        p.write_text(new_text, encoding="utf-8")
        from ..agent.checkpoints import track_modified_file as _track

        _track(p)
        lint_err = lint_after_write(p, new_text)
        suffix = f" (fuzzy: score={match.score:.3f}, matched {match.end - match.start} chars)"
        if lint_err:
            return (
                f"edited {p}: replaced 1 occurrence{suffix} "
                f"but failed validation: {lint_err}. "
                "Fix the syntax and re-call Edit."
            )
        verify_tail = _verify_after_write(p)
        return (
            f"edited {p}: replaced 1 occurrence{suffix} "
            f"({len(old_string)} -> {len(new_string)} chars)"
            + verify_tail
        )
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
    from ..agent.checkpoints import track_modified_file as _track

    _track(p)
    lint_err = lint_after_write(p, new_text)
    if lint_err:
        return (
            f"edited {p}: replaced {replacements} occurrence(s) "
            f"but failed validation: {lint_err}. "
            "Fix the syntax and re-call Edit."
        )
    verify_tail = _verify_after_write(p)
    return (
        f"edited {p}: replaced {replacements} occurrence(s) "
        f"({len(old_string)} -> {len(new_string)} chars each)"
        + verify_tail
    )


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
    p = _resolve(path, intent="read")
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
