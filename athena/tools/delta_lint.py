"""Post-write syntax check for files written by tools.

A tool that writes a Python / JSON / YAML / TOML file calls
:func:`lint_after_write` with the path and the new content. If the parser
rejects the content, the tool returns a structured error to the model so
it can fix the syntax and retry — silent garbage on disk is the failure
mode this exists to prevent.

Coverage is intentionally narrow: only formats whose parsers are cheap and
in-tree. Markdown, plain text, and source files in other languages pass
through unchecked.
"""

from __future__ import annotations

import ast
import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore


logger = logging.getLogger(__name__)

CheckFn = Callable[[str], str | None]


def _check_python(text: str) -> str | None:
    try:
        ast.parse(text)
        return None
    except SyntaxError as e:
        return f"SyntaxError at line {e.lineno}: {e.msg}"


def _check_json(text: str) -> str | None:
    try:
        json.loads(text)
        return None
    except json.JSONDecodeError as e:
        return f"JSONDecodeError at line {e.lineno}, col {e.colno}: {e.msg}"


def _check_yaml(text: str) -> str | None:
    try:
        yaml.safe_load(text)
        return None
    except yaml.YAMLError as e:
        return f"YAMLError: {e}"


def _check_toml(text: str) -> str | None:
    try:
        tomllib.loads(text)
        return None
    except tomllib.TOMLDecodeError as e:
        return f"TOMLDecodeError: {e}"


_CHECKS: dict[str, CheckFn] = {
    ".py": _check_python,
    ".pyi": _check_python,
    ".json": _check_json,
    ".yaml": _check_yaml,
    ".yml": _check_yaml,
    ".toml": _check_toml,
}


def lint_after_write(path: Path, content: str) -> str | None:
    """Return an error string if ``content`` fails to parse for ``path``'s
    extension, else ``None``. Empty content passes for all formats — the
    Write tool already had to choose to write nothing, and an empty file
    is a valid Python/JSON/YAML/TOML file."""
    if not content:
        return None
    check = _CHECKS.get(path.suffix.lower())
    if check is None:
        return None
    return check(content.lstrip("﻿"))
