"""File-ops capability bucket.

The agent gets a workspace pre-populated with some files and a
prompt asking it to perform a filesystem mutation. Verification
walks the workspace afterward to check whether the mutation
landed correctly.

Each task is deterministic: the prompt names exact files/lines,
the verifier checks exact filesystem state. No string-matching
on assistant text — the only thing that matters is whether the
files look right.
"""

from __future__ import annotations

from pathlib import Path

from ..task import EvalTask, VerifyContext

_BUCKET = "file_ops"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# ---------------------------------------------------------------------------
# 1. Create a single new file with exact content
# ---------------------------------------------------------------------------


def _setup_empty(ws: Path) -> None:
    pass


def _verify_create_hello(ctx: VerifyContext) -> bool:
    target = ctx.workspace / "hello.txt"
    return target.exists() and "Hello, athena" in _read(target)


_create_hello = EvalTask(
    id="file_ops.create_hello",
    prompt=(
        "Create a file named hello.txt in the current workspace containing exactly: Hello, athena"
    ),
    setup_fn=_setup_empty,
    verify_fn=_verify_create_hello,
    bucket=_BUCKET,
    description="Create a new file with a specific content line.",
)


# ---------------------------------------------------------------------------
# 2. Rename an existing file
# ---------------------------------------------------------------------------


def _setup_for_rename(ws: Path) -> None:
    (ws / "old_name.txt").write_text("payload here\n", encoding="utf-8")


def _verify_rename(ctx: VerifyContext) -> bool:
    ws = ctx.workspace
    return (
        not (ws / "old_name.txt").exists()
        and (ws / "new_name.txt").exists()
        and "payload here" in _read(ws / "new_name.txt")
    )


_rename_file = EvalTask(
    id="file_ops.rename_file",
    prompt=("Rename old_name.txt to new_name.txt in the current workspace. Preserve its contents."),
    setup_fn=_setup_for_rename,
    verify_fn=_verify_rename,
    bucket=_BUCKET,
    description="Rename a file, preserving its contents.",
)


# ---------------------------------------------------------------------------
# 3. Append a line to an existing file
# ---------------------------------------------------------------------------


def _setup_for_append(ws: Path) -> None:
    (ws / "notes.md").write_text("# Notes\n\n- first item\n", encoding="utf-8")


def _verify_append(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "notes.md")
    return "- first item" in text and "- second item" in text


_append_line = EvalTask(
    id="file_ops.append_line",
    prompt=(
        "Append a new bullet '- second item' to notes.md in the current "
        "workspace, preserving the existing '- first item' line."
    ),
    setup_fn=_setup_for_append,
    verify_fn=_verify_append,
    bucket=_BUCKET,
    description="Append a line without destroying existing content.",
)


# ---------------------------------------------------------------------------
# 4. Replace a specific string in a file
# ---------------------------------------------------------------------------


def _setup_for_replace(ws: Path) -> None:
    (ws / "greeting.py").write_text('def greet():\n    return "hello world"\n', encoding="utf-8")


def _verify_replace(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "greeting.py")
    return '"hello athena"' in text and '"hello world"' not in text


_replace_string = EvalTask(
    id="file_ops.replace_string",
    prompt=(
        'In greeting.py, change the string "hello world" to '
        '"hello athena". Don\'t change anything else in the file.'
    ),
    setup_fn=_setup_for_replace,
    verify_fn=_verify_replace,
    bucket=_BUCKET,
    description="Targeted string replacement.",
)


# ---------------------------------------------------------------------------
# 5. Delete a file
# ---------------------------------------------------------------------------


def _setup_for_delete(ws: Path) -> None:
    (ws / "keep.txt").write_text("keep me\n", encoding="utf-8")
    (ws / "trash.txt").write_text("delete me\n", encoding="utf-8")


def _verify_delete(ctx: VerifyContext) -> bool:
    ws = ctx.workspace
    return not (ws / "trash.txt").exists() and (ws / "keep.txt").exists()


_delete_file = EvalTask(
    id="file_ops.delete_file",
    prompt=("Delete trash.txt from the current workspace. Do not touch keep.txt."),
    setup_fn=_setup_for_delete,
    verify_fn=_verify_delete,
    bucket=_BUCKET,
    description="Delete a specific file without touching others.",
)


# ---------------------------------------------------------------------------
# 6. Create a nested directory and a file inside it
# ---------------------------------------------------------------------------


def _verify_nested(ctx: VerifyContext) -> bool:
    target = ctx.workspace / "src" / "main.py"
    return target.exists() and "def main" in _read(target)


_create_nested = EvalTask(
    id="file_ops.create_nested",
    prompt=(
        "Create a directory called src in the current workspace and "
        "inside it create main.py containing a function named main "
        "that returns the integer 42."
    ),
    setup_fn=_setup_empty,
    verify_fn=_verify_nested,
    bucket=_BUCKET,
    description="Create a nested dir + a Python file inside it.",
)


# ---------------------------------------------------------------------------
# 7. Find and modify a function across files
# ---------------------------------------------------------------------------


def _setup_for_find_and_modify(ws: Path) -> None:
    (ws / "math_a.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (ws / "math_b.py").write_text("def multiply(a, b):\n    return a * b\n", encoding="utf-8")


def _verify_find_and_modify(ctx: VerifyContext) -> bool:
    a = _read(ctx.workspace / "math_a.py")
    b = _read(ctx.workspace / "math_b.py")
    # add() must now have a docstring; multiply() must NOT be modified.
    add_has_doc = '"""' in a and "def add" in a
    multiply_unchanged = "def multiply" in b and '"""' not in b
    return add_has_doc and multiply_unchanged


_find_and_modify = EvalTask(
    id="file_ops.find_and_modify",
    prompt=(
        "In the current workspace there are two files: math_a.py and "
        "math_b.py. Find the function named add (it's in one of them) "
        "and add a one-line docstring describing what it does. Leave "
        "the other function untouched."
    ),
    setup_fn=_setup_for_find_and_modify,
    verify_fn=_verify_find_and_modify,
    bucket=_BUCKET,
    description="Locate a function by name, modify only that file.",
)


# ---------------------------------------------------------------------------
# 8. Move a file between directories
# ---------------------------------------------------------------------------


def _setup_for_move(ws: Path) -> None:
    (ws / "src").mkdir()
    (ws / "dst").mkdir()
    (ws / "src" / "data.json").write_text('{"k": 1}\n', encoding="utf-8")


def _verify_move(ctx: VerifyContext) -> bool:
    ws = ctx.workspace
    src = ws / "src" / "data.json"
    dst = ws / "dst" / "data.json"
    return (not src.exists()) and dst.exists() and '"k"' in _read(dst)


_move_file = EvalTask(
    id="file_ops.move_file",
    prompt=(
        "Move data.json from the src/ directory to the dst/ directory "
        "in the current workspace. Preserve its contents."
    ),
    setup_fn=_setup_for_move,
    verify_fn=_verify_move,
    bucket=_BUCKET,
    description="Move a file across subdirectories.",
)


# ---------------------------------------------------------------------------
# 9. Add an import to an existing Python file
# ---------------------------------------------------------------------------


def _setup_for_import(ws: Path) -> None:
    (ws / "script.py").write_text("def now_ts():\n    return time.time()\n", encoding="utf-8")


def _verify_import(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "script.py")
    return "import time" in text and "def now_ts" in text


_add_import = EvalTask(
    id="file_ops.add_import",
    prompt=(
        "script.py uses time.time() but doesn't import time. Add the "
        "missing 'import time' line at the top of script.py."
    ),
    setup_fn=_setup_for_import,
    verify_fn=_verify_import,
    bucket=_BUCKET,
    description="Add a missing import to a Python file.",
)


# ---------------------------------------------------------------------------
# 10. Concatenate two files into a third
# ---------------------------------------------------------------------------


def _setup_for_concat(ws: Path) -> None:
    (ws / "part_a.txt").write_text("alpha\n", encoding="utf-8")
    (ws / "part_b.txt").write_text("beta\n", encoding="utf-8")


def _verify_concat(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "combined.txt")
    return "alpha" in text and "beta" in text and text.index("alpha") < text.index("beta")


_concat_files = EvalTask(
    id="file_ops.concat_files",
    prompt=(
        "Create combined.txt in the current workspace containing the "
        "contents of part_a.txt followed by the contents of part_b.txt, "
        "in that order."
    ),
    setup_fn=_setup_for_concat,
    verify_fn=_verify_concat,
    bucket=_BUCKET,
    description="Concatenate two files in order into a third.",
)


# ---------------------------------------------------------------------------
# 11. Add a trailing newline to a file missing one
# ---------------------------------------------------------------------------


def _setup_for_newline(ws: Path) -> None:
    # No trailing newline on purpose.
    (ws / "no_eol.txt").write_text("last line without newline", encoding="utf-8")


def _verify_newline(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "no_eol.txt")
    return text.endswith("\n") and "last line without newline" in text


_add_trailing_newline = EvalTask(
    id="file_ops.add_trailing_newline",
    prompt=(
        "no_eol.txt is missing a trailing newline. Edit the file so "
        "that it ends with exactly one newline character. Don't add "
        "any other content."
    ),
    setup_fn=_setup_for_newline,
    verify_fn=_verify_newline,
    bucket=_BUCKET,
    description="Add exactly one trailing newline.",
)


# ---------------------------------------------------------------------------
# 12. Update a JSON value via parse-modify-write
# ---------------------------------------------------------------------------


def _setup_for_json_value(ws: Path) -> None:
    (ws / "config.json").write_text('{\n  "name": "old",\n  "version": 1\n}\n', encoding="utf-8")


def _verify_json_value(ctx: VerifyContext) -> bool:
    import json as _json

    try:
        data = _json.loads(_read(ctx.workspace / "config.json"))
    except _json.JSONDecodeError:
        return False
    return bool(data.get("name") == "new" and data.get("version") == 1)


_update_json_value = EvalTask(
    id="file_ops.update_json_value",
    prompt=(
        "In config.json, change the value of the 'name' field from "
        "'old' to 'new'. Keep the 'version' field unchanged. The file "
        "must remain valid JSON."
    ),
    setup_fn=_setup_for_json_value,
    verify_fn=_verify_json_value,
    bucket=_BUCKET,
    description="Update a JSON field value, keep validity.",
)


# ---------------------------------------------------------------------------
# 13. Comment out a single line in a Python file
# ---------------------------------------------------------------------------


def _setup_for_comment_out(ws: Path) -> None:
    (ws / "buggy.py").write_text(
        "x = 1\nprint('debug:', x)\ny = x * 2\n",
        encoding="utf-8",
    )


def _verify_comment_out(ctx: VerifyContext) -> bool:
    lines = _read(ctx.workspace / "buggy.py").splitlines()
    # The print line should be commented out (starts with #).
    has_commented_print = any(l.strip().startswith("#") and "print" in l for l in lines)
    # The other lines should still be there.
    has_x = any("x = 1" in l and not l.strip().startswith("#") for l in lines)
    has_y = any("y = x * 2" in l and not l.strip().startswith("#") for l in lines)
    return has_commented_print and has_x and has_y


_comment_out_line = EvalTask(
    id="file_ops.comment_out_line",
    prompt=("In buggy.py, comment out the line that calls print(). Leave every other line as-is."),
    setup_fn=_setup_for_comment_out,
    verify_fn=_verify_comment_out,
    bucket=_BUCKET,
    description="Comment out a specific line in a Python file.",
)


# ---------------------------------------------------------------------------
# 14. Create a file with a specific number of lines
# ---------------------------------------------------------------------------


def _verify_n_lines(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "five.txt")
    if not text:
        return False
    # Five non-empty lines (trailing newline is fine).
    lines = [l for l in text.splitlines() if l.strip()]
    return len(lines) == 5


_create_five_lines = EvalTask(
    id="file_ops.create_five_lines",
    prompt=(
        "Create five.txt in the current workspace containing exactly "
        "five non-empty lines. Each line should say 'line N' where N "
        "is the line number from 1 to 5."
    ),
    setup_fn=_setup_empty,
    verify_fn=_verify_n_lines,
    bucket=_BUCKET,
    description="Generate a file with N lines following a pattern.",
)


# ---------------------------------------------------------------------------
# 15. Read-then-modify: rewrite a list of imports alphabetically
# ---------------------------------------------------------------------------


def _setup_for_sort_imports(ws: Path) -> None:
    (ws / "messy.py").write_text(
        "import zlib\nimport os\nimport json\nimport sys\n\ndef run():\n    pass\n",
        encoding="utf-8",
    )


def _verify_sort_imports(ctx: VerifyContext) -> bool:
    lines = _read(ctx.workspace / "messy.py").splitlines()
    import_lines = [l for l in lines if l.startswith("import ")]
    if len(import_lines) != 4:
        return False
    names = [l.replace("import ", "") for l in import_lines]
    # Function body should be intact.
    has_run = any("def run" in l for l in lines)
    return names == sorted(names) and has_run


_sort_imports = EvalTask(
    id="file_ops.sort_imports",
    prompt=(
        "In messy.py, sort the four import lines at the top "
        "alphabetically. Don't change anything else in the file."
    ),
    setup_fn=_setup_for_sort_imports,
    verify_fn=_verify_sort_imports,
    bucket=_BUCKET,
    description="Sort import lines alphabetically.",
)


# ---------------------------------------------------------------------------
# Catalogue export
# ---------------------------------------------------------------------------


TASKS: list[EvalTask] = [
    _create_hello,
    _rename_file,
    _append_line,
    _replace_string,
    _delete_file,
    _create_nested,
    _find_and_modify,
    _move_file,
    _add_import,
    _concat_files,
    _add_trailing_newline,
    _update_json_value,
    _comment_out_line,
    _create_five_lines,
    _sort_imports,
]

__all__ = ["TASKS"]
