"""Obsidian vault tools — a model-facing surface athena can interface with
directly to read and write notes in an Obsidian vault.

An Obsidian vault is just a directory of Markdown files, so these tools
operate on the filesystem directly — no Obsidian CLI, plugin, or running
app required. They ARE Obsidian-aware: YAML frontmatter (properties/tags),
``[[wikilinks]]`` and ``#tags`` (preserved verbatim in note bodies),
title-based note resolution across subfolders, and daily notes.

Tools (toolset ``obsidian``):

  * ``obsidian_write``  — create / overwrite / append a note (+ frontmatter, tags)
  * ``obsidian_read``   — read a note back (frontmatter + body)
  * ``obsidian_append`` — append a block to a note (optionally under a heading)
  * ``obsidian_search`` — full-text search the vault (empty query → list notes)
  * ``obsidian_daily``  — append to (or create) today's daily note

All five are gated by ``_vault_ready`` (a ``check_fn``): they only appear in
the model's tool list when ``cfg.obsidian_vault_path`` is set and points at an
existing directory. Writes resolve strictly inside the vault — a path that
escapes the vault root is refused.

Configure with, in ``~/.athena/config.toml``::

    obsidian_vault_path = "C:/Users/you/Documents/MyVault"
    obsidian_daily_folder = "Daily"          # optional; "" = vault root
    obsidian_daily_date_format = "%Y-%m-%d"  # optional
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from ._active_cfg import active_cfg
from .registry import tool

_MAX_BODY = 256_000

# ---- vault resolution ------------------------------------------------------


def _vault() -> Path | None:
    """The configured vault root, or None when unset."""
    raw = getattr(active_cfg(), "obsidian_vault_path", None)
    if not raw:
        return None
    return Path(str(raw)).expanduser()


def _vault_ready() -> bool:
    """check_fn gate: tools are advertised only when the vault exists."""
    v = _vault()
    return v is not None and v.is_dir()


def _not_configured() -> str:
    return (
        "ERROR: obsidian not configured. Set `obsidian_vault_path` in "
        "~/.athena/config.toml to your vault directory, then retry."
    )


def _normalize_note(note: str) -> str:
    """Normalize a note reference to a vault-relative ``*.md`` path string.

    Accepts a bare title (``My Note``), a relative path (``Folder/My Note``),
    or one already ending in ``.md``. Forward and back slashes both work.
    """
    n = note.strip().replace("\\", "/").lstrip("/")
    if not n.lower().endswith(".md"):
        n += ".md"
    return n


def _resolve_in_vault(vault: Path, note: str) -> Path:
    """Resolve ``note`` to an absolute path strictly inside ``vault``.

    Raises ValueError if the resolved path escapes the vault (``..`` traversal
    or an absolute path pointing elsewhere).
    """
    rel = _normalize_note(note)
    candidate = (vault / rel).resolve()
    vault_root = vault.resolve()
    if vault_root != candidate and vault_root not in candidate.parents:
        raise ValueError(f"path escapes the vault: {note!r}")
    return candidate


def _find_existing(vault: Path, note: str) -> Path | None:
    """Locate an existing note by exact relative path, else by title anywhere
    in the vault (first match, breadth-ish via sorted rglob)."""
    direct = _resolve_in_vault(vault, note)
    if direct.is_file():
        return direct
    # Bare-title fallback: search the whole vault for <title>.md.
    target = _normalize_note(note).rsplit("/", 1)[-1].lower()
    matches = sorted(p for p in vault.rglob("*.md") if p.name.lower() == target)
    return matches[0] if matches else None


def _obsidian_uri(vault: Path, path: Path) -> str:
    """An ``obsidian://open`` URI the user can click to open the note."""
    try:
        rel = path.resolve().relative_to(vault.resolve()).as_posix()
    except ValueError:
        rel = path.name
    return f"obsidian://open?vault={quote(vault.name)}&file={quote(rel)}"


# ---- frontmatter -----------------------------------------------------------


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a note into (frontmatter dict, body). No frontmatter → ({}, text)."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}, text
    # Find the closing fence on its own line.
    lines = text.splitlines(keepends=True)
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    raw = "".join(lines[1:end])
    body = "".join(lines[end + 1 :])
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return data, body.lstrip("\n")


def _compose(frontmatter: dict[str, Any], body: str) -> str:
    """Render frontmatter + body into a note string."""
    if not frontmatter:
        return body if body.endswith("\n") or not body else body + "\n"
    fm = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{fm}\n---\n\n{body.lstrip(chr(10))}".rstrip("\n") + "\n"


def _merge_tags(frontmatter: dict[str, Any], tags: list[str] | None) -> dict[str, Any]:
    if not tags:
        return frontmatter
    existing = frontmatter.get("tags") or []
    if isinstance(existing, str):
        existing = [existing]
    merged: list[str] = list(dict.fromkeys([*existing, *tags]))  # de-dup, keep order
    return {**frontmatter, "tags": merged}


# ---- tools -----------------------------------------------------------------


@tool(
    name="obsidian_write",
    toolset="obsidian",
    description=(
        "Create, overwrite, or append to a note in the Obsidian vault. "
        "`note` is a title (resolved to <title>.md at the vault root) or a "
        "vault-relative path like 'Projects/Athena'. Use `[[wikilinks]]` and "
        "`#tags` directly in `content` — they're preserved. `frontmatter` "
        "(object) and `tags` (array) populate YAML properties Obsidian reads. "
        "mode: 'create' (fail if exists), 'overwrite', or 'append'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "note": {"type": "string", "description": "Title or vault-relative path."},
            "content": {"type": "string", "description": "Markdown body."},
            "frontmatter": {
                "type": "object",
                "description": "YAML properties (e.g. {'aliases': [...], 'status': 'wip'}).",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags merged into frontmatter `tags`.",
            },
            "mode": {
                "type": "string",
                "enum": ["create", "overwrite", "append"],
                "description": "Default 'create'.",
            },
        },
        "required": ["note", "content"],
    },
    requires_confirmation=True,
    check_fn=_vault_ready,
)
def obsidian_write(
    note: str,
    content: str = "",
    frontmatter: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    mode: str = "create",
) -> str:
    vault = _vault()
    if vault is None or not vault.is_dir():
        return _not_configured()
    try:
        path = _resolve_in_vault(vault, note)
    except ValueError as e:
        return f"ERROR: {e}"

    if mode == "append" and path.is_file():
        existing = path.read_text(encoding="utf-8")
        fm, body = _split_frontmatter(existing)
        fm = _merge_tags(fm, tags)
        if frontmatter:
            fm = {**fm, **frontmatter}
        new_body = body.rstrip("\n") + "\n\n" + content.strip() + "\n"
        path.write_text(_compose(fm, new_body), encoding="utf-8")
        return f"appended to {path} ({len(content)} chars)\n{_obsidian_uri(vault, path)}"

    if mode == "create" and path.is_file():
        return (
            f"ERROR: note already exists: {path}. Use mode='overwrite' to replace "
            "or mode='append' to add to it."
        )

    fm = _merge_tags(dict(frontmatter or {}), tags)
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.is_file()
    path.write_text(_compose(fm, content), encoding="utf-8")
    verb = "overwrote" if existed else "created"
    return f"{verb} {path} ({len(content)} chars)\n{_obsidian_uri(vault, path)}"


@tool(
    name="obsidian_read",
    toolset="obsidian",
    aliases=["obsidian_open"],
    description=(
        "Read a note from the Obsidian vault. `note` is a title (found "
        "anywhere in the vault) or a vault-relative path. Returns the YAML "
        "frontmatter (if any) followed by the Markdown body."
    ),
    parameters={
        "type": "object",
        "properties": {
            "note": {"type": "string", "description": "Title or vault-relative path."},
        },
        "required": ["note"],
    },
    parallel_safe=True,
    check_fn=_vault_ready,
)
def obsidian_read(note: str) -> str:
    vault = _vault()
    if vault is None or not vault.is_dir():
        return _not_configured()
    try:
        found = _find_existing(vault, note)
    except ValueError as e:
        return f"ERROR: {e}"
    if found is None:
        return f"ERROR: note not found in vault: {note!r}"
    text = found.read_text(encoding="utf-8")
    if len(text) > _MAX_BODY:
        text = text[:_MAX_BODY] + "\n... [truncated] ..."
    rel = found.resolve().relative_to(vault.resolve()).as_posix()
    return f"# {rel}\n\n{text}"


@tool(
    name="obsidian_append",
    toolset="obsidian",
    description=(
        "Append a block of Markdown to an existing note (creating it if "
        "missing). Optionally place it under a `## heading` (appended if the "
        "heading isn't already present). Good for running notes / logs / "
        "captures. Use `[[wikilinks]]` and `#tags` freely."
    ),
    parameters={
        "type": "object",
        "properties": {
            "note": {"type": "string", "description": "Title or vault-relative path."},
            "content": {"type": "string", "description": "Markdown to append."},
            "heading": {
                "type": "string",
                "description": "Optional H2 section to append under (created if absent).",
            },
        },
        "required": ["note", "content"],
    },
    requires_confirmation=True,
    check_fn=_vault_ready,
)
def obsidian_append(note: str, content: str, heading: str | None = None) -> str:
    vault = _vault()
    if vault is None or not vault.is_dir():
        return _not_configured()
    try:
        path = _find_existing(vault, note) or _resolve_in_vault(vault, note)
    except ValueError as e:
        return f"ERROR: {e}"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    block = content.strip()
    if heading:
        hdr = f"## {heading}"
        if hdr not in existing:
            block = f"{hdr}\n\n{block}"
    new_text = (existing.rstrip("\n") + "\n\n" + block + "\n") if existing else block + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    created = not path.is_file()
    path.write_text(new_text, encoding="utf-8")
    verb = "created + wrote" if created else "appended to"
    return f"{verb} {path} ({len(content)} chars)\n{_obsidian_uri(vault, path)}"


@tool(
    name="obsidian_search",
    toolset="obsidian",
    description=(
        "Search the Obsidian vault. With a `query`, returns notes whose path "
        "or content contains it (case-insensitive), with the first matching "
        "line. With an empty query, lists notes in the vault. Use this to find "
        "the right note before reading or appending."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Text to find; empty lists notes."},
            "limit": {"type": "integer", "description": "Max results (default 25)."},
        },
    },
    parallel_safe=True,
    check_fn=_vault_ready,
)
def obsidian_search(query: str = "", limit: int = 25) -> str:
    vault = _vault()
    if vault is None or not vault.is_dir():
        return _not_configured()
    q = query.strip().lower()
    limit = max(1, min(limit, 200))
    notes = sorted(vault.rglob("*.md"))
    results: list[dict[str, str]] = []
    for p in notes:
        rel = p.resolve().relative_to(vault.resolve()).as_posix()
        if not q:
            results.append({"note": rel})
        else:
            hit_line = ""
            in_path = q in rel.lower()
            try:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if q in line.lower():
                        hit_line = line.strip()[:200]
                        break
            except OSError:
                continue
            if in_path or hit_line:
                results.append({"note": rel, "match": hit_line or "(filename match)"})
        if len(results) >= limit:
            break
    if not results:
        what = f"matching {query!r}" if q else "found"
        return f"no notes {what} in vault"
    header = f"{len(results)} note(s)" + (f" matching {query!r}" if q else "") + ":"
    return header + "\n" + json.dumps(results, indent=2, ensure_ascii=False)


@tool(
    name="obsidian_daily",
    toolset="obsidian",
    description=(
        "Append a timestamped-or-plain block to today's daily note in the "
        "vault (created if it doesn't exist yet). Path is "
        "<vault>/<obsidian_daily_folder>/<date>.md. Optionally place the block "
        "under a `## heading`."
    ),
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Markdown to add to today's note."},
            "heading": {
                "type": "string",
                "description": "Optional H2 section to append under.",
            },
        },
        "required": ["content"],
    },
    requires_confirmation=True,
    check_fn=_vault_ready,
)
def obsidian_daily(content: str, heading: str | None = None) -> str:
    vault = _vault()
    if vault is None or not vault.is_dir():
        return _not_configured()
    cfg = active_cfg()
    folder = str(getattr(cfg, "obsidian_daily_folder", "") or "").strip("/")
    fmt = str(getattr(cfg, "obsidian_daily_date_format", "%Y-%m-%d") or "%Y-%m-%d")
    stamp = datetime.now().strftime(fmt)
    rel = f"{folder}/{stamp}" if folder else stamp
    return obsidian_append(rel, content, heading=heading)
