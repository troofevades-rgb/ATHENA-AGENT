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
        "delete archives (moves to .archive/) — true deletion is out of band."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "patch", "delete", "unarchive", "pin", "unpin", "write_file"],
            },
            "name": {"type": "string"},
            "frontmatter": {"type": "object"},
            "body": {"type": "string"},
            "file_path": {
                "type": "string",
                "description": "For write_file: relative path under skill dir (references/foo.md, templates/x.py, scripts/y.sh).",
            },
            "file_content": {"type": "string"},
            "absorbed_into": {
                "type": "string",
                "description": (
                    "For delete: name of umbrella skill that absorbed this one's "
                    "content. Empty string = pruned with no forwarding target. "
                    "Required for curator-origin deletes."
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
            if not file_path or file_content is None:
                return _err(action, name, "write_file requires file_path and file_content")
            manager.skill_write_file(name, file_path, file_content, workspace)
            return _ok(action, name, f"wrote {file_path}")

        return _err(action, name, f"unknown action {action!r}")
    except (SkillExistsError, SkillNotFoundError, CuratorPolicyError, ValueError) as e:
        return _err(action, name, f"{type(e).__name__}: {e}")
