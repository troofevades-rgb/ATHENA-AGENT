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
import re
from typing import Any

from ..skills import manager
from ..skills.archive import SkillNotFoundError
from ..skills.discovery import discover_skills
from ..skills.frontmatter import parse_frontmatter
from ..skills.manager import CuratorPolicyError, SkillExistsError
from ..skills.verify import verify_body
from . import file_ops
from .registry import tool


def _workspace():
    return file_ops._WORKSPACE


# -----------------------------------------------------------------------------
# Topic-consistency guard for skill_manage patch
# -----------------------------------------------------------------------------

# Stopwords + tool-noun filler that wouldn't be meaningful evidence of
# topic match. Kept short on purpose — we want WORDS like "OSINT" and
# "GEPA" to be the signal, not "the" and "a".
_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "into", "have",
    "has", "are", "was", "were", "but", "not", "use", "uses", "using",
    "your", "you", "all", "any", "out", "over", "via", "per", "via",
    "skill", "skills", "tool", "tools", "code", "data", "info",
    "research", "analysis", "assistant", "guide", "general",
    "implementation", "implement", "framework", "module", "system",
    "public", "private", "user", "users", "list", "show", "create",
    "delete", "view", "manage", "patch", "update", "write", "read",
    "file", "files", "directory", "path", "name", "type",
})


def _tokens(s: str) -> set[str]:
    """Lowercase, alnum-only tokens 3+ chars long, minus stopwords."""
    if not s:
        return set()
    return {
        w for w in re.findall(r"[a-z0-9]{3,}", s.lower())
        if w not in _STOPWORDS
    }


def _first_h1(body: str) -> str:
    """Return the text of the first ``# Heading`` line, or empty string."""
    for ln in body.splitlines():
        stripped = ln.lstrip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _check_body_matches_skill(
    *,
    body: str,
    skill_name: str,
    skill_description: str,
) -> tuple[bool, str, set[str]]:
    """Soft topic-match check between a patch body and the target skill.

    Returns ``(matches, h1, h1_tokens)``:
      * ``matches`` — True when the body's first H1 shares at least one
        meaningful word with the skill's name or description, OR when
        the body has no H1 to check.
      * ``h1`` — the H1 text (or empty)
      * ``h1_tokens`` — the meaningful tokens extracted from the H1

    Not a security check — it's a "did you mean to write THIS into THAT?"
    guard. Designed to catch the literal real-world bug observed at
    2026-05-22T01:12:20 where an agent patched the ``osint-research``
    skill with a body titled "GEPA Self-Improvement Analyzer" — total
    topic mismatch the existing pipeline accepted silently.
    """
    h1 = _first_h1(body)
    if not h1:
        return True, "", set()
    h1_tokens = _tokens(h1)
    if not h1_tokens:
        return True, h1, set()
    skill_tokens = _tokens(f"{skill_name} {skill_description}")
    if not skill_tokens:
        # Skill has no description-side tokens to compare against —
        # can't reason about match, so allow.
        return True, h1, h1_tokens
    return bool(h1_tokens & skill_tokens), h1, h1_tokens


def _skill_metadata(skill_name: str, workspace) -> tuple[str, str] | None:
    """Read the target skill's frontmatter for the topic-match check.
    Returns (name, description) or None if the skill doesn't exist.

    Uses ``discover_skills`` so the caller doesn't have to re-implement
    the workspace/user-dir layered lookup — same code path the agent
    uses for its catalog.
    """
    try:
        catalog = discover_skills(workspace=workspace)
    except Exception:
        return None
    entry = catalog.get(skill_name)
    if entry is None:
        return None
    fm, _source = entry
    return fm.name or skill_name, fm.description or ""


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
        "alongside the SKILL.md.\n"
        "\n"
        "EXAMPLE — create a skill (copy + modify):\n"
        '  skill_manage(\n'
        '      action="create",\n'
        '      name="osint-research",\n'
        '      frontmatter={\n'
        '          "description": "OSINT research framework for "\n'
        '                         "gathering public information"\n'
        '      },\n'
        '      body="# OSINT Research Skill\\n\\nThis skill ..."\n'
        "  )\n"
        "\n"
        "EXAMPLE — patch a skill's body without touching frontmatter:\n"
        '  skill_manage(\n'
        '      action="patch",\n'
        '      name="osint-research",\n'
        '      body="# OSINT Research Skill\\n\\n(rewritten body)"\n'
        "  )\n"
        "\n"
        "EXAMPLE — add a support file alongside SKILL.md:\n"
        '  skill_manage(\n'
        '      action="write_file",\n'
        '      name="osint-research",\n'
        '      file_path="references/checklist.md",\n'
        '      file_content="# Checklist\\n- ..."\n'
        "  )"
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
                # JSONSchema-level constraint: when the dict is
                # supplied at all, `description` (when present)
                # must be a non-empty string. The conditional
                # "required only on create" rule is enforced
                # by the pre-flight in the handler — JSONSchema
                # can't express "required when action=='create'"
                # without if/then/else schemas that not every
                # planner respects.
                "properties": {
                    "description": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1024,
                        "description": (
                            "One-line summary of what the skill does. "
                            "Required for action='create'."
                        ),
                    },
                    "name": {
                        "type": "string",
                        "description": (
                            "Optional inside frontmatter — the top-level "
                            "`name` kwarg is the source of truth."
                        ),
                    },
                },
                "additionalProperties": True,
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
    # Body verify gate (create + patch): any ```python fenced block in
    # the body must parse with ast.parse before we accept the write.
    # A broken code block in an active skill is worse than no skill —
    # future calls trust the skill's example and copy the broken code.
    if action in ("create", "patch") and body is not None:
        ok, msg = verify_body(body)
        if not ok:
            return _err(action, name, msg)
    # Topic-consistency gate (patch only): a body whose first H1 shares
    # no meaningful words with the target skill's name + description
    # is almost always a "patched the wrong slot" mistake. We refuse
    # UNLESS the same call also updates the description (frontmatter)
    # — that explicit double-touch is the agent's way of saying
    # "yes, I really mean to repurpose this skill."
    #
    # The literal incident this guards against: 2026-05-22T01:12:20,
    # ``skill_manage(action='patch', name='osint-research',
    # body='# GEPA Self-Improvement Analyzer\n...')`` — model meant to
    # create a separate GEPA skill but targeted the OSINT slot. The
    # patch went through silently, leaving a skill whose frontmatter
    # said OSINT and whose body was GEPA code. Subsequent skill_view
    # calls returned the GEPA body and the model would loop trying to
    # "find the right OSINT skill" because the one it loaded didn't
    # match its name.
    if action == "patch" and body is not None and (
        not frontmatter or not str((frontmatter or {}).get("description", "")).strip()
    ):
        meta = _skill_metadata(name, workspace)
        if meta is not None:
            skill_name_meta, skill_description = meta
            matches, h1, h1_tokens = _check_body_matches_skill(
                body=body,
                skill_name=skill_name_meta,
                skill_description=skill_description,
            )
            if not matches:
                return _err(
                    "patch", name,
                    f"refused: body H1 {h1!r} shares no keywords with "
                    f"skill {skill_name_meta!r} (description: "
                    f"{skill_description!r}). This usually means "
                    f"you're patching the wrong skill slot. If you "
                    f"really intend to repurpose this skill, include "
                    f"a frontmatter description update in the same "
                    f"call so the metadata stays consistent — e.g. "
                    f"`frontmatter={{'description': '...new topic...'}}`. "
                    f"Otherwise call skill_manage with the correct "
                    f"target name (perhaps action='create' for a new "
                    f"skill).",
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
