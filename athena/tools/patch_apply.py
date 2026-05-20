"""``patch_apply`` tool: apply a unified-diff patch atomically across files.

The tool accepts a multi-hunk, multi-file unified diff (the output
of ``diff -u``) and applies every hunk. If ANY hunk fails (context
mismatch, target file missing, OS error during write), every file
touched so far is rolled back from a temp backup. Net effect:
either the whole patch lands or no file is modified.

Path security: each ``new_path`` is routed through
``path_security.validate_path(intent="write")`` so writes outside
the workspace require the same approval as a direct ``Write`` call.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from ..safety.path_security import validate_path
from .patch_parser import PatchParseError, apply_patch_to_text, parse_patch
from .registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="patch_apply",
    toolset="file",
    description=(
        "Apply a unified-diff patch (the output of `diff -u`) to one or "
        "more files. All hunks across all files apply atomically — "
        "either every hunk lands or NO files are modified (per-file "
        "backup + restore on partial failure). Use for multi-callsite "
        "renames, multi-line refactors, and any edit that would "
        "otherwise require more than two str_replace calls."
    ),
    parameters={
        "type": "object",
        "properties": {
            "patch": {
                "type": "string",
                "description": (
                    "The unified diff text. Must start with `--- a/path` "
                    "and `+++ b/path` headers; each hunk must include "
                    "context lines that match the file content exactly. "
                    "Multi-file patches: include multiple --- / +++ "
                    "header pairs."
                ),
            }
        },
        "required": ["patch"],
    },
    requires_confirmation=True,
)
def patch_apply(patch: str = "") -> str:
    if not patch or not patch.strip():
        return "ERROR: empty patch"

    try:
        parsed = parse_patch(patch)
    except PatchParseError as e:
        return f"ERROR: patch parse error: {e}"

    if not parsed.files:
        return "ERROR: patch contained no file sections"

    # Validate every target path BEFORE touching anything so a deny
    # decision aborts the whole operation cleanly.
    targets: list[Path] = []
    for fp in parsed.files:
        try:
            target = validate_path(fp.new_path, intent="write")
        except Exception as e:
            return f"ERROR: path_security refused {fp.new_path}: {e}"
        if not target.exists():
            return f"ERROR: target file does not exist: {target}"
        targets.append(target)

    backups: list[tuple[Path, Path]] = []
    applied: list[Path] = []
    try:
        for fp, target in zip(parsed.files, targets, strict=True):
            with tempfile.NamedTemporaryFile(suffix=".bak", delete=False) as backup_f:
                backup_path = Path(backup_f.name)
            shutil.copyfile(target, backup_path)
            backups.append((backup_path, target))

            original = target.read_text(encoding="utf-8")
            new_text = apply_patch_to_text(original, fp)
            target.write_text(new_text, encoding="utf-8")
            applied.append(target)
            logger.info("patch_apply: %s (%d hunks)", target, len(fp.hunks))
    except (PatchParseError, OSError) as e:
        for backup_path, target in backups:
            try:
                shutil.copyfile(backup_path, target)
            except OSError:
                logger.exception("failed to restore %s from backup", target)
        for backup_path, _ in backups:
            backup_path.unlink(missing_ok=True)
        return f"ERROR: patch failed and rolled back: {e}"

    for backup_path, _ in backups:
        backup_path.unlink(missing_ok=True)

    total_hunks = sum(len(fp.hunks) for fp in parsed.files)
    file_list = ", ".join(str(p) for p in applied)
    return f"applied {total_hunks} hunk(s) across {len(applied)} file(s): {file_list}"
