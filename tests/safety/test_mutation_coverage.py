"""Guard: every content mutation in the skill / memory stores is
snapshotted + audited.

``safety/mutation.py:snapshot_and_record`` is the chokepoint — a
context manager that takes a rollback snapshot and writes a
MutationRecord. skills/manager.py and memory/providers/builtin_file.py
are the two modules that actually write user content, and the
convention is that every such write happens inside a
``with snapshot_and_record(...)`` block.

That convention was by-eye. This test makes it checked: it walks each
module's AST and asserts every file-write primitive (``write_text`` /
``write_bytes`` / ``secure_write_*`` / ``open(..., "w")``) is either
inside a ``snapshot_and_record`` with-block OR in an explicitly
exempted function. The exemption list is the documented escape hatch
for DERIVED writes (the MEMORY.md index, reproducible from the .md
files) that aren't user-content mutations — a new mutation path that
forgets the snapshot fails here instead of silently bypassing audit +
rollback.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Functions whose writes are DERIVED / non-mutation and so don't need a
# snapshot. Keep this list tiny and justified — adding to it is opting
# a write out of the audit+rollback guarantee.
_EXEMPT: dict[str, set[str]] = {
    "athena/skills/manager.py": set(),
    "athena/memory/providers/builtin_file.py": {
        # MEMORY.md index: a derived, one-line-per-entry index rebuilt
        # from the .md files and written atomically (tmp + os.replace).
        # Not user content; reproducible — no rollback point needed.
        "_refresh_markdown_index",
    },
}

_WRITE_ATTRS = {"write_text", "write_bytes"}
_WRITE_FUNCS = {"secure_write_json", "secure_write_text", "secure_write_bytes"}


def _is_snapshot_with(node: ast.With) -> bool:
    for item in node.items:
        expr = item.context_expr
        if isinstance(expr, ast.Call):
            f = expr.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name == "snapshot_and_record":
                return True
    return False


def _write_kind(node: ast.AST) -> str | None:
    """Return a label if ``node`` is a file-write primitive call, else None."""
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    if isinstance(f, ast.Attribute):
        if f.attr in _WRITE_ATTRS or f.attr in _WRITE_FUNCS:
            return f.attr
    elif isinstance(f, ast.Name):
        if f.id in _WRITE_FUNCS:
            return f.id
        if f.id == "open":
            mode = _open_mode(node)
            if mode and any(c in mode for c in "wax"):
                return f"open({mode})"
    return None


def _open_mode(call: ast.Call) -> str | None:
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        return str(call.args[1].value)
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return None  # mode unknown → treat as read (don't flag)


def _unguarded_writes(source: str, exempt: set[str]) -> list[tuple[str, int, str]]:
    """Return (function, lineno, kind) for every write primitive that is
    neither inside a snapshot_and_record block nor in an exempt func."""
    tree = ast.parse(source)
    out: list[tuple[str, int, str]] = []

    def walk(node: ast.AST, *, in_snapshot: bool, func: str | None) -> None:
        kind = _write_kind(node)
        if kind and not in_snapshot and func not in exempt:
            out.append((func or "<module>", getattr(node, "lineno", -1), kind))
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                # Function boundary: snapshot scope doesn't cross it.
                walk(child, in_snapshot=False, func=child.name)
            elif isinstance(child, ast.With) and _is_snapshot_with(child):
                walk(child, in_snapshot=True, func=func)
            else:
                walk(child, in_snapshot=in_snapshot, func=func)

    walk(tree, in_snapshot=False, func=None)
    return out


def test_mutation_writes_are_snapshotted() -> None:
    problems: dict[str, list[tuple[str, int, str]]] = {}
    for rel, exempt in _EXEMPT.items():
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        bad = _unguarded_writes(src, exempt)
        if bad:
            problems[rel] = bad
    assert not problems, (
        "Found file-write(s) outside a snapshot_and_record block (and not in "
        "the derived-write exemption list). Wrap the mutation in "
        "`with snapshot_and_record(...) as ctx:` + `ctx.record(path)`, or — if "
        "it's a derived/non-mutation write — add the function to _EXEMPT with a "
        f"justification:\n{problems}"
    )


def test_guard_detects_an_unguarded_write() -> None:
    """The walker actually flags a bare write (so the guard can't silently
    pass by being a no-op)."""
    src = (
        "from pathlib import Path\n"
        "def mutate(p):\n"
        "    Path(p).write_text('x')\n"
    )
    bad = _unguarded_writes(src, set())
    assert bad == [("mutate", 3, "write_text")]


def test_guard_accepts_write_inside_snapshot_block() -> None:
    src = (
        "def mutate(p):\n"
        "    with snapshot_and_record([p], tool_name='t') as ctx:\n"
        "        p.write_text('x')\n"
        "        ctx.record(p)\n"
    )
    assert _unguarded_writes(src, set()) == []


def test_guard_honors_exemption() -> None:
    src = "def _refresh_index(p):\n    p.write_text('x')\n"
    assert _unguarded_writes(src, {"_refresh_index"}) == []
