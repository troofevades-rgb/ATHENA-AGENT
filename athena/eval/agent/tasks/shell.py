"""Multi-step shell capability bucket.

Tasks that require the agent to chain shell operations: count
files, walk directories, build dir trees, initialize a git repo
and commit. Verification reads disk state after the agent
finishes.

All tasks declare ``required_tools=["core"]`` so the agent has
Bash + file ops available. Shell-only tasks where the model
might be tempted to use Write/Edit instead still verify on disk
state, so either path passes as long as the world ends in the
right shape.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..task import EvalTask, VerifyContext

_BUCKET = "shell"
_TOOLS = ["core"]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# ---------------------------------------------------------------------------
# 1. Count files in a directory
# ---------------------------------------------------------------------------


def _setup_for_count(ws: Path) -> None:
    for i in range(7):
        (ws / f"f{i}.txt").write_text("", encoding="utf-8")


def _verify_count(ctx: VerifyContext) -> bool:
    # The agent should write the count to count.txt — verify that file
    # exists and contains "7".
    text = _read(ctx.workspace / "count.txt").strip()
    return text == "7"


_count_files = EvalTask(
    id="shell.count_files",
    prompt=(
        "There are several files in the current workspace. Count "
        "them and write the count (as a plain integer, no other text) "
        "to count.txt."
    ),
    setup_fn=_setup_for_count,
    verify_fn=_verify_count,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="Count files, write the count to a file.",
)


# ---------------------------------------------------------------------------
# 2. Build a specific 3-directory tree
# ---------------------------------------------------------------------------


def _verify_dir_tree(ctx: VerifyContext) -> bool:
    ws = ctx.workspace
    expected = ["a", "b", "c"]
    return all((ws / d).is_dir() for d in expected) and (ws / "a" / "leaf.txt").exists()


_build_dir_tree = EvalTask(
    id="shell.build_dir_tree",
    prompt=(
        "Create three directories named a, b, and c in the current "
        "workspace. Inside directory a, create a file called leaf.txt."
    ),
    setup_fn=lambda ws: None,
    verify_fn=_verify_dir_tree,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="Build a small directory tree from scratch.",
)


# ---------------------------------------------------------------------------
# 3. Git init + commit
# ---------------------------------------------------------------------------


def _setup_for_git_init(ws: Path) -> None:
    (ws / "README.md").write_text("# Test\n", encoding="utf-8")


def _verify_git_init(ctx: VerifyContext) -> bool:
    git_dir = ctx.workspace / ".git"
    if not git_dir.is_dir():
        return False
    # A commit exists if HEAD resolves to something.
    head = git_dir / "HEAD"
    if not head.exists():
        return False
    # Look for at least one ref under refs/heads.
    refs = git_dir / "refs" / "heads"
    return refs.exists() and any(refs.iterdir())


_git_init_commit = EvalTask(
    id="shell.git_init_commit",
    prompt=(
        "Initialize a new git repository in the current workspace. "
        "Add the existing README.md file. Make an initial commit with "
        "the message 'initial commit'. Configure git user.email to "
        "'eval@example.com' and user.name to 'eval-bot' for this "
        "repository so the commit succeeds."
    ),
    setup_fn=_setup_for_git_init,
    verify_fn=_verify_git_init,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="git init + add + commit.",
    timeout_s=90.0,  # Git can be slow on Windows.
)


# ---------------------------------------------------------------------------
# 4. Find files by extension
# ---------------------------------------------------------------------------


def _setup_for_find_py(ws: Path) -> None:
    (ws / "a.py").write_text("", encoding="utf-8")
    (ws / "b.py").write_text("", encoding="utf-8")
    (ws / "c.txt").write_text("", encoding="utf-8")
    (ws / "sub").mkdir()
    (ws / "sub" / "d.py").write_text("", encoding="utf-8")


def _verify_find_py(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "found.txt").strip().splitlines()
    names = sorted(p.strip() for p in text)
    # Three .py files exist. Accept full paths or basenames.
    basenames = sorted(Path(p).name for p in names)
    return basenames == ["a.py", "b.py", "d.py"]


_find_by_extension = EvalTask(
    id="shell.find_by_extension",
    prompt=(
        "List every .py file in the current workspace (including "
        "subdirectories), one path per line, and write that list to "
        "found.txt. No .txt files should appear in the output."
    ),
    setup_fn=_setup_for_find_py,
    verify_fn=_verify_find_py,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="Recursive file find filtered by extension.",
)


# ---------------------------------------------------------------------------
# 5. Compute total file size
# ---------------------------------------------------------------------------


def _setup_for_size(ws: Path) -> None:
    (ws / "a.bin").write_bytes(b"X" * 100)
    (ws / "b.bin").write_bytes(b"Y" * 250)


def _verify_size(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "size.txt").strip()
    # Accept "350" or "350 bytes" etc.; just the digit must appear.
    return "350" in text


_total_size = EvalTask(
    id="shell.total_size",
    prompt=(
        "Compute the total size in bytes of all files in the current "
        "workspace and write the number to size.txt. (Two files: "
        "a.bin and b.bin.)"
    ),
    setup_fn=_setup_for_size,
    verify_fn=_verify_size,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="Sum file sizes, write the total.",
)


# ---------------------------------------------------------------------------
# 6. Copy a file under a new name
# ---------------------------------------------------------------------------


def _setup_for_copy(ws: Path) -> None:
    (ws / "original.dat").write_bytes(b"important payload")


def _verify_copy(ctx: VerifyContext) -> bool:
    ws = ctx.workspace
    orig = ws / "original.dat"
    backup = ws / "original.dat.bak"
    if not orig.exists() or not backup.exists():
        return False
    return orig.read_bytes() == backup.read_bytes() == b"important payload"


_copy_file = EvalTask(
    id="shell.copy_file",
    prompt=(
        "Make a backup copy of original.dat in the current workspace, "
        "named original.dat.bak. Both files should exist afterward with "
        "identical contents."
    ),
    setup_fn=_setup_for_copy,
    verify_fn=_verify_copy,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="Copy a file under a new name.",
)


# ---------------------------------------------------------------------------
# 7. Set up a Python package skeleton
# ---------------------------------------------------------------------------


def _verify_package_skeleton(ctx: VerifyContext) -> bool:
    ws = ctx.workspace
    pkg = ws / "mypkg"
    return (
        pkg.is_dir()
        and (pkg / "__init__.py").exists()
        and (pkg / "core.py").exists()
    )


_python_package = EvalTask(
    id="shell.python_package",
    prompt=(
        "Create a Python package directory called mypkg in the current "
        "workspace. It should contain two files: __init__.py (empty is "
        "fine) and core.py (also empty is fine)."
    ),
    setup_fn=lambda ws: None,
    verify_fn=_verify_package_skeleton,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="Create a Python package directory skeleton.",
)


# ---------------------------------------------------------------------------
# 8. Concatenate logs in order
# ---------------------------------------------------------------------------


def _setup_for_log_concat(ws: Path) -> None:
    (ws / "log_001.txt").write_text("first event\n", encoding="utf-8")
    (ws / "log_002.txt").write_text("second event\n", encoding="utf-8")
    (ws / "log_003.txt").write_text("third event\n", encoding="utf-8")


def _verify_log_concat(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "all_logs.txt")
    first = text.find("first event")
    second = text.find("second event")
    third = text.find("third event")
    return first != -1 and second > first and third > second


_concat_logs_in_order = EvalTask(
    id="shell.concat_logs_in_order",
    prompt=(
        "Concatenate log_001.txt, log_002.txt, and log_003.txt (in that "
        "numerical order) into a single file called all_logs.txt in the "
        "current workspace."
    ),
    setup_fn=_setup_for_log_concat,
    verify_fn=_verify_log_concat,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="Concatenate files in a specific order.",
)


# ---------------------------------------------------------------------------
# 9. Filter lines by pattern
# ---------------------------------------------------------------------------


def _setup_for_grep(ws: Path) -> None:
    (ws / "log.txt").write_text(
        "INFO: starting up\n"
        "ERROR: bad input\n"
        "INFO: ready\n"
        "ERROR: timeout\n"
        "INFO: shutdown\n",
        encoding="utf-8",
    )


def _verify_grep(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "errors.txt")
    lines = [l for l in text.splitlines() if l.strip()]
    return (
        len(lines) == 2
        and all("ERROR" in l for l in lines)
        and "bad input" in text
        and "timeout" in text
    )


_filter_errors = EvalTask(
    id="shell.filter_errors",
    prompt=(
        "In the current workspace there's a log.txt file with mixed "
        "INFO and ERROR lines. Write only the lines containing 'ERROR' "
        "to errors.txt, preserving order."
    ),
    setup_fn=_setup_for_grep,
    verify_fn=_verify_grep,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="Filter lines from a file by pattern.",
)


# ---------------------------------------------------------------------------
# 10. Replace a string across multiple files
# ---------------------------------------------------------------------------


def _setup_for_bulk_replace(ws: Path) -> None:
    for name in ("a.txt", "b.txt", "c.txt"):
        (ws / name).write_text("hello world\nsecond line\n", encoding="utf-8")


def _verify_bulk_replace(ctx: VerifyContext) -> bool:
    ws = ctx.workspace
    for name in ("a.txt", "b.txt", "c.txt"):
        text = _read(ws / name)
        if "hello world" in text or "hello athena" not in text:
            return False
    return True


_bulk_replace = EvalTask(
    id="shell.bulk_replace",
    prompt=(
        "In every .txt file in the current workspace (a.txt, b.txt, "
        "c.txt), replace 'hello world' with 'hello athena'. Don't "
        "touch the second line of any file."
    ),
    setup_fn=_setup_for_bulk_replace,
    verify_fn=_verify_bulk_replace,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="Apply the same string replacement to several files.",
)


# ---------------------------------------------------------------------------
# 11. Create a file from a list of values
# ---------------------------------------------------------------------------


def _verify_squares(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "squares.txt")
    # Expect lines "1", "4", "9", "16", "25" (order matters).
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines == ["1", "4", "9", "16", "25"]


_compute_and_write = EvalTask(
    id="shell.compute_and_write",
    prompt=(
        "Create squares.txt in the current workspace with five lines: "
        "the squares of the integers 1 through 5, one per line, in "
        "ascending order. (So: 1, 4, 9, 16, 25.)"
    ),
    setup_fn=lambda ws: None,
    verify_fn=_verify_squares,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="Compute and write a deterministic numeric sequence.",
)


# ---------------------------------------------------------------------------
# 12. Move all files matching a pattern into a subdirectory
# ---------------------------------------------------------------------------


def _setup_for_archive(ws: Path) -> None:
    for name in ("doc_a.md", "doc_b.md", "image.png"):
        (ws / name).write_text("", encoding="utf-8")


def _verify_archive(ctx: VerifyContext) -> bool:
    ws = ctx.workspace
    archive = ws / "archive"
    if not archive.is_dir():
        return False
    return (
        (archive / "doc_a.md").exists()
        and (archive / "doc_b.md").exists()
        and (ws / "image.png").exists()
        and not (ws / "doc_a.md").exists()
        and not (ws / "doc_b.md").exists()
    )


_archive_pattern = EvalTask(
    id="shell.archive_pattern",
    prompt=(
        "Move every file ending in .md in the current workspace into "
        "a new subdirectory called archive. Don't move files with "
        "other extensions."
    ),
    setup_fn=_setup_for_archive,
    verify_fn=_verify_archive,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="Move pattern-matching files into a subdir.",
)


# ---------------------------------------------------------------------------
# 13. Read a value and write a derived value
# ---------------------------------------------------------------------------


def _setup_for_double(ws: Path) -> None:
    (ws / "n.txt").write_text("21\n", encoding="utf-8")


def _verify_double(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "doubled.txt").strip()
    return text == "42"


_double_value = EvalTask(
    id="shell.double_value",
    prompt=(
        "n.txt contains a single integer. Read it, double it, and "
        "write the result to doubled.txt as a plain integer."
    ),
    setup_fn=_setup_for_double,
    verify_fn=_verify_double,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="Read, transform, write — minimal end-to-end shell flow.",
)


# ---------------------------------------------------------------------------
# 14. Tag a directory tree with a summary file
# ---------------------------------------------------------------------------


def _setup_for_summary(ws: Path) -> None:
    for name in ("a.txt", "b.txt", "c.txt"):
        (ws / name).write_text("x", encoding="utf-8")


def _verify_summary(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "SUMMARY.md")
    return all(name in text for name in ("a.txt", "b.txt", "c.txt"))


_dir_summary = EvalTask(
    id="shell.dir_summary",
    prompt=(
        "Create SUMMARY.md in the current workspace listing every "
        "other file in the workspace, one per line."
    ),
    setup_fn=_setup_for_summary,
    verify_fn=_verify_summary,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="List directory contents in a markdown summary file.",
)


# ---------------------------------------------------------------------------
# 15. Make a script executable (Unix-only behavior; on Windows the
#     verifier just checks the file exists with expected contents).
# ---------------------------------------------------------------------------


def _setup_for_make_script(ws: Path) -> None:
    pass


def _verify_make_script(ctx: VerifyContext) -> bool:
    script = ctx.workspace / "run.sh"
    if not script.exists():
        return False
    text = _read(script)
    return text.startswith("#!") and "echo" in text


_make_script = EvalTask(
    id="shell.make_script",
    prompt=(
        "Create a shell script called run.sh in the current workspace. "
        "It should start with a shebang line (#!/bin/sh or similar) "
        "and contain an echo command that prints 'ready'."
    ),
    setup_fn=_setup_for_make_script,
    verify_fn=_verify_make_script,
    required_tools=_TOOLS,
    bucket=_BUCKET,
    description="Create a simple shell script with shebang.",
)


TASKS: list[EvalTask] = [
    _count_files,
    _build_dir_tree,
    _git_init_commit,
    _find_by_extension,
    _total_size,
    _copy_file,
    _python_package,
    _concat_logs_in_order,
    _filter_errors,
    _bulk_replace,
    _compute_and_write,
    _archive_pattern,
    _double_value,
    _dir_summary,
    _make_script,
]

__all__ = ["TASKS"]
