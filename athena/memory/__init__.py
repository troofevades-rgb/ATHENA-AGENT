"""Persistent memory system, mirroring Claude Code's `~/.claude/projects/<path>/memory/`.

Layout per workspace:

    ~/.athena/projects/<workspace-slug>/memory/
        MEMORY.md              # one-line index, auto-loaded into system prompt
        user_role.md           # individual memory file
        feedback_testing.md
        project_rewrite.md
        ...

Each memory file has frontmatter:

    ---
    name: short title
    description: one-line description used to decide relevance
    type: user | feedback | project | reference
    ---
    body...

MEMORY.md is the index, NOT a memory itself. Entries look like:

    - [Title](filename.md) — one-line hook

The agent loads MEMORY.md into the system prompt every session. Individual
memory files are read on demand by the model via the Read tool.

Phase 5 added :mod:`athena.memory.providers` and :class:`MemoryProvider` for
profile-keyed, pluggable backends. This module's workspace-keyed functions
(``load_memory_index``, ``list_memories``, ``write_memory``,
``delete_memory``, ``parse_memory_file``, ``render_index_for_display``) are
the legacy public surface — preserved so existing callers (agent system
prompt build, ``/memory`` command, migration importer) keep working.
Phase 14 will migrate them over to the profile-keyed surface.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from ..config import CONFIG_DIR

PROJECTS_DIR = CONFIG_DIR / "projects"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)
_MEMORY_TYPES = {"user", "feedback", "project", "reference"}


def _slugify(p: Path) -> str:
    """Stable, filesystem-safe slug for a workspace path.

    A short hash of the resolved path is appended so distinct paths that share
    the same letterform (e.g. '/a/b-c' and '/a/b/c') don't collide and end up
    sharing a memory directory.
    """
    s = str(p.resolve())
    base = re.sub(r"[^a-zA-Z0-9._-]", "_", s.strip("/").replace("/", "-")) or "root"
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]
    return f"{base}_{h}"


def memory_dir(workspace: Path) -> Path:
    return PROJECTS_DIR / _slugify(workspace) / "memory"


def ensure_memory_dir(workspace: Path) -> Path:
    d = memory_dir(workspace)
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_memory_index(workspace: Path) -> str | None:
    """Return MEMORY.md content for this workspace, or None if absent.

    This is what gets injected into the system prompt every session.
    """
    index = memory_dir(workspace) / "MEMORY.md"
    if not index.exists():
        return None
    try:
        text = index.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.strip():
        return None
    # Truncate to 200 lines (Claude Code's documented limit) to keep context lean
    lines = text.splitlines()
    if len(lines) > 200:
        lines = lines[:200] + ["", "<!-- index truncated at 200 lines -->"]
    return "\n".join(lines)


@dataclass
class MemoryFile:
    path: Path
    name: str
    description: str
    type: str
    body: str


def parse_memory_file(path: Path) -> MemoryFile | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    fm_block = m.group(1)
    body = m.group(2)
    fields: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = v.strip()
        # Strip matching surrounding quotes if present (YAML-style)
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        fields[k.strip()] = v
    return MemoryFile(
        path=path,
        name=fields.get("name", path.stem),
        description=fields.get("description", ""),
        type=fields.get("type", "user"),
        body=body.strip(),
    )


def list_memories(workspace: Path) -> list[MemoryFile]:
    d = memory_dir(workspace)
    if not d.exists():
        return []
    out: list[MemoryFile] = []
    for p in sorted(d.iterdir()):
        if p.name == "MEMORY.md" or not p.suffix == ".md":
            continue
        mf = parse_memory_file(p)
        if mf:
            out.append(mf)
    return out


def write_memory(
    workspace: Path,
    *,
    filename: str,
    name: str,
    description: str,
    type: str,
    body: str,
) -> Path:
    """Write a memory file and update MEMORY.md to reference it."""
    if type not in _MEMORY_TYPES:
        raise ValueError(f"invalid memory type {type!r}; must be one of {_MEMORY_TYPES}")
    if not filename.endswith(".md"):
        filename += ".md"
    if filename == "MEMORY.md":
        raise ValueError("cannot use MEMORY.md as a memory filename")

    d = ensure_memory_dir(workspace)
    target = d / filename
    content = (
        f"---\nname: {name}\ndescription: {description}\ntype: {type}\n---\n\n{body.strip()}\n"
    )
    target.write_text(content, encoding="utf-8")
    _refresh_index(d)
    return target


def delete_memory(workspace: Path, filename: str) -> bool:
    d = memory_dir(workspace)
    target = d / filename
    if not target.exists():
        return False
    target.unlink()
    _refresh_index(d)
    return True


def _refresh_index(memory_directory: Path) -> None:
    """Rebuild MEMORY.md from the parsed memory files in the directory."""
    entries: list[str] = ["# MEMORY index", ""]
    for p in sorted(memory_directory.iterdir()):
        if p.name == "MEMORY.md" or p.suffix != ".md":
            continue
        mf = parse_memory_file(p)
        if not mf:
            continue
        # One-liner: - [Title](file.md) — type: hook
        line = f"- [{mf.name}]({p.name}) — {mf.type}: {mf.description}"
        # Cap each line at ~200 chars so the index stays scannable
        if len(line) > 200:
            line = line[:197] + "..."
        entries.append(line)
    (memory_directory / "MEMORY.md").write_text("\n".join(entries) + "\n", encoding="utf-8")


# ---- CLI helpers (used by /memory) --------------------------------------


def render_index_for_display(workspace: Path) -> str:
    mems = list_memories(workspace)
    if not mems:
        return f"(no memories at {memory_dir(workspace)})"
    lines = [f"memory dir: {memory_dir(workspace)}", ""]
    for mf in mems:
        lines.append(f"  • [{mf.type}] {mf.path.name} — {mf.name}")
        if mf.description:
            lines.append(f"        {mf.description}")
    return "\n".join(lines)
