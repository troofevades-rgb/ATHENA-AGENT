"""Model-facing skill tools.

Three tools live here, all under ``toolset="skills"``:

- ``skills_list``  — read-only catalog browse
- ``skill_view``   — read full SKILL.md body
- ``skill_manage`` — create / patch / delete / unarchive / pin / unpin /
                     write_file. Confirmation-gated; forks auto-deny.

Workspace context is read from the file_ops module's global, which the
Agent sets at startup. That keeps the tool signatures simple and aligned
with how ``Read`` / ``Write`` / ``Edit`` already operate.
"""

from __future__ import annotations

import json
from typing import Any

from ..skills import manager
from ..skills.archive import SkillNotFoundError
from ..skills.discovery import discover_skills
from ..skills.manager import CuratorPolicyError, SkillExistsError
from . import file_ops
from .registry import tool


def _workspace():
    return file_ops._WORKSPACE


def _ok(action: str, name: str, message: str = "") -> str:
    return json.dumps(
        {
            "success": True,
            "target": "skill",
            "action": action,
            "skill_name": name,
            "message": message,
        }
    )


def _err(action: str, name: str, message: str) -> str:
    return json.dumps(
        {
            "success": False,
            "target": "skill",
            "action": action,
            "skill_name": name,
            "message": message,
        }
    )


@tool(
    name="skills_list",
    toolset="skills",
    description=(
        "List installed skills. Optionally filter by state (active|stale|"
        "archived|all; default active) or by pinned. Returns a concise "
        "markdown list of name, state, pinned flag, and one-line description."
    ),
    parameters={
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "enum": ["active", "stale", "archived", "all"],
                "description": "Filter by skill state (default: active).",
            },
            "pinned": {
                "type": "boolean",
                "description": "If set, only return pinned (true) or non-pinned (false) skills.",
            },
        },
    },
)
def skills_list(state: str = "active", pinned: bool | None = None) -> str:
    include_archived = state in ("archived", "all")
    catalog = discover_skills(_workspace(), include_archived=include_archived)

    rows: list[tuple[str, str, bool, str]] = []
    for name, (fm, _dir) in sorted(catalog.items()):
        if state not in ("all",) and fm.state != state:
            continue
        if pinned is not None and fm.pinned != pinned:
            continue
        rows.append((name, fm.state, fm.pinned, fm.description))

    if not rows:
        return "(no skills match the filter)"

    lines = []
    for n, s, p, d in rows:
        marker = " [pinned]" if p else ""
        lines.append(f"- {n}{marker} ({s}) — {d}")
    return "\n".join(lines)


@tool(
    name="skill_view",
    toolset="skills",
    description=(
        "Read a skill's full SKILL.md (frontmatter + body). Use this to "
        "load a skill's contents on demand — the system prompt only shows "
        "the catalog, not the full bodies."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name (slug)."},
        },
        "required": ["name"],
    },
)
def skill_view(name: str) -> str:
    text = manager.skill_view(name, _workspace())
    if text is None:
        return f"ERROR: no skill named {name!r}"
    return text


@tool(
    name="skill_manage",
    toolset="skills",
    description=(
        "Create, modify, archive, pin, or write support files to a skill. "
        "Actions: create | patch | delete | unarchive | pin | unpin | write_file. "
        "delete archives (moves to .archive/) — true deletion is out of band. "
        "\n\n"
        "PER-ACTION REQUIRED ARGS (in addition to action + name):\n"
        "  create     → frontmatter MUST contain a non-empty `description` "
        "key (frontmatter['description']); body is the SKILL.md content.\n"
        "  patch      → frontmatter (partial updates dict) and/or body. "
        "Whatever you pass replaces; whatever you omit stays.\n"
        "  delete     → absorbed_into (optional but required for curator-"
        "origin deletes; empty string = no forwarding target).\n"
        "  unarchive  → no extra args.\n"
        "  pin / unpin → no extra args.\n"
        "  write_file → file_path AND file_content. NOT for SKILL.md "
        "itself — use action='patch' with body=... for the body. "
        "write_file is for references/*.md / templates/*.* / scripts/*.* "
        "alongside the SKILL.md."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "patch", "delete", "unarchive", "pin", "unpin", "write_file"],
                "description": (
                    "What to do. Each action has its own required args — see "
                    "the tool description for the per-action checklist."
                ),
            },
            "name": {
                "type": "string",
                "description": "Skill name (slug). Top-level kwarg, not inside frontmatter.",
            },
            "frontmatter": {
                "type": "object",
                "description": (
                    "Skill frontmatter dict. For action='create' this MUST "
                    "include a non-empty `description` key (the skill's one-line "
                    "summary, ≤ 1024 chars); the `name` key is optional inside "
                    "frontmatter — the top-level `name` kwarg is the source of "
                    "truth. For action='patch' this is a PARTIAL updates dict "
                    "(omitted keys retain prior values). Ignored for other "
                    "actions."
                ),
            },
            "body": {
                "type": "string",
                "description": (
                    "The skill body (SKILL.md content) — markdown, freeform. "
                    "Used by action='create' (initial body) and "
                    "action='patch' (replaces existing body). NOT for support "
                    "files (use action='write_file' for those)."
                ),
            },
            "file_path": {
                "type": "string",
                "description": (
                    "For action='write_file' ONLY: relative path under the "
                    "skill dir (references/foo.md, templates/x.py, "
                    "scripts/y.sh). Required together with file_content."
                ),
            },
            "file_content": {
                "type": "string",
                "description": (
                    "For action='write_file' ONLY: file contents. Required "
                    "together with file_path (passing file_path alone errors)."
                ),
            },
            "absorbed_into": {
                "type": "string",
                "description": (
                    "For action='delete': name of umbrella skill that absorbed "
                    "this one's content. Empty string = pruned with no "
                    "forwarding target. Required for curator-origin deletes."
                ),
            },
        },
        "required": ["action", "name"],
    },
    requires_confirmation=True,
)
def skill_manage(
    action: str,
    name: str,
    frontmatter: dict[str, Any] | None = None,
    body: str | None = None,
    file_path: str | None = None,
    file_content: str | None = None,
    absorbed_into: str | None = None,
) -> str:
    workspace = _workspace()
    # Pre-flight check for create: surface the most common
    # mistake (`description` passed as a top-level kwarg or
    # missing from frontmatter) with a fix hint INSTEAD of
    # the generic FrontmatterError. The agent's first call
    # is much more likely to land correctly.
    if action == "create":
        fm = frontmatter or {}
        if not isinstance(fm, dict) or not str(fm.get("description", "")).strip():
            return _err(
                "create",
                name,
                "create requires frontmatter={'description': '...', ...}. "
                "Pass `description` as a key INSIDE frontmatter (not as a "
                "top-level kwarg).",
            )
    # Same for write_file: surface the file_path+file_content
    # pair requirement explicitly when only one is passed.
    if action == "write_file":
        if not file_path or file_content is None:
            return _err(
                action,
                name,
                "write_file requires BOTH file_path and file_content. "
                "(For the SKILL.md body, use action='patch' with body=...; "
                "write_file is for support files like references/foo.md.)",
            )

    try:
        if action == "create":
            manager.skill_create(name, frontmatter or {}, body or "", workspace)
            return _ok("create", name, "skill created")

        if action == "patch":
            manager.skill_patch(
                name,
                body=body,
                frontmatter_updates=frontmatter or None,
                workspace=workspace,
            )
            return _ok("patch", name, "skill patched")

        if action == "delete":
            manager.skill_delete(name, workspace, absorbed_into=absorbed_into)
            return _ok("delete", name, "skill archived")

        if action == "unarchive":
            manager.skill_unarchive(name, workspace)
            return _ok("unarchive", name, "skill restored")

        if action == "pin":
            manager.skill_pin(name, workspace)
            return _ok("pin", name, "skill pinned")

        if action == "unpin":
            manager.skill_unpin(name, workspace)
            return _ok("unpin", name, "skill unpinned")

        if action == "write_file":
            # Pre-flight above already checked file_path +
            # file_content are both present.
            manager.skill_write_file(name, file_path, file_content, workspace)
            return _ok(action, name, f"wrote {file_path}")

        return _err(action, name, f"unknown action {action!r}")
    except (SkillExistsError, SkillNotFoundError, CuratorPolicyError, ValueError) as e:
        return _err(action, name, f"{type(e).__name__}: {e}")
