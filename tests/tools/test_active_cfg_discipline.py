"""Drift-guard: tools route config reads through ``active_cfg()``,
not ``load_config()`` directly.

ATHENA.md / CLAUDE.md document the convention: tools should read the
LIVE agent's cfg via :func:`athena.tools._active_cfg.active_cfg` so
session-scoped mutations (``/allowlist add``, sandbox toggles, recall-
mode flips, ``/godmode apply``, etc.) are visible mid-session. A tool
that calls ``load_config()`` directly bypasses the live cfg and reads
the on-disk snapshot -- mutations made via slash commands won't take
effect until the next ``Agent`` construction.

The auditing-agent run on this session flagged this as a smell. The
codebase is mostly clean: every tool except the explicitly-documented
test-monkeypatch seam in ``diagnose.py`` goes through ``active_cfg``.

This pin enforces the convention by scanning every file under
``athena/tools/`` for ``load_config`` references:

  * Allowed: ``active_cfg`` callers, the ``_active_cfg`` module
    itself, ``diagnose.py`` (deliberately exposes ``load_config``
    as a monkeypatchable symbol -- 5 LSP tests bind to that name).
  * Banned: any other tool importing or calling ``load_config``
    directly.

If a new tool needs config, it imports ``active_cfg`` from
``._active_cfg`` and calls it. This test catches the regression.
"""

from __future__ import annotations

import re
from pathlib import Path

_TOOLS_DIR = Path(__file__).parent.parent.parent / "athena" / "tools"

# Files where ``load_config`` references are intentional and approved.
# Keep this list small and document each entry.
_LOAD_CONFIG_ALLOWLIST: frozenset[str] = frozenset(
    {
        # The helper itself -- it IS the centralised disk fallback that
        # every other tool goes through.
        "_active_cfg.py",
        # The LSP tool exposes ``load_config`` as a module-level symbol
        # for test monkeypatching. Five tests in tests/lsp/test_tool.py
        # patch it. The agent-first branch in ``_resolve_cfg`` is the
        # primary path; the load_config fallback is the test seam.
        "diagnose.py",
    }
)


def _python_files_under(directory: Path) -> list[Path]:
    """Recursively list every .py under ``directory`` (excluding the
    __pycache__/ dirs)."""
    return [
        p
        for p in directory.rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def test_no_tool_imports_load_config_outside_allowlist() -> None:
    """Reading code only: scan ``from ..config import load_config``
    style imports. A new tool that needs config goes through
    ``active_cfg()`` instead."""
    pattern = re.compile(
        r"from\s+\.\.config\s+import\s+[\w,\s]*\bload_config\b"
        r"|from\s+athena\.config\s+import\s+[\w,\s]*\bload_config\b",
    )
    offenders: list[str] = []
    for path in _python_files_under(_TOOLS_DIR):
        if path.name in _LOAD_CONFIG_ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            offenders.append(path.name)
    assert not offenders, (
        f"These tool modules import load_config directly instead of "
        f"going through ``active_cfg()``: {offenders}. Tools must "
        "read the LIVE agent's cfg so session-scoped mutations "
        "(/allowlist add, /godmode apply, etc.) are visible "
        "mid-session. Use ``from ._active_cfg import active_cfg`` "
        "and call ``active_cfg()`` instead. If the new tool "
        "really needs the test-monkeypatch seam, add it to the "
        "_LOAD_CONFIG_ALLOWLIST with a comment justifying the "
        "exception."
    )


def test_no_tool_calls_load_config_outside_allowlist() -> None:
    """Belt-and-suspenders -- catch ``athena.config.load_config()``
    call sites that import via a non-from path."""
    # ``load_config()`` followed by an open paren -- the call, not
    # just the reference. We exclude:
    #   * Comment lines (split on ``#``).
    #   * Docstring code references that wrap the call in markdown
    #     backticks (`` `load_config()` ``). Real Python code has
    #     no backticks; a backtick on the line is a tell that the
    #     match is inside a doc string explaining historical
    #     behavior, not an actual call site.
    pattern = re.compile(r"\bload_config\s*\(")
    offenders: list[tuple[str, int, str]] = []
    for path in _python_files_under(_TOOLS_DIR):
        if path.name in _LOAD_CONFIG_ALLOWLIST:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.split("#", 1)[0]
            if "`" in stripped:
                continue
            if pattern.search(stripped):
                offenders.append((path.name, lineno, line.strip()))
    assert not offenders, (
        f"These tools CALL load_config() outside the allowlist: "
        f"{offenders}. Use ``active_cfg()`` instead."
    )
