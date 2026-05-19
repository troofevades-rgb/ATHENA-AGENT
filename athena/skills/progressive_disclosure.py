"""Progressive disclosure of the skill catalog into the system prompt.

The agent injects only a one-line-per-skill catalog at session start. Full
SKILL.md bodies are loaded on demand via the ``skill_view`` tool. This keeps
context cheap even when the user has dozens of skills installed.

Pinned skills sort to the top of the active section so they get the model's
attention first. Archived skills are omitted entirely — they don't exist
from the model's perspective unless ``skills_list state=archived`` is called.
"""

from __future__ import annotations

from pathlib import Path

from .discovery import discover_skills

_CATALOG_HEADER = (
    "# Skills available\n"
    "Use the `skill_view` tool to load a skill's full body, or `skill_manage`\n"
    "to create / patch / archive skills. Pinned skills appear first."
)

_TRAILER = "\n... and {n} more skills (use `skills_list` to see all)."


def _line(name: str, pinned: bool, state: str, description: str) -> str:
    marker = " [pinned]" if pinned else ""
    state_marker = "" if state == "active" else f" (state: {state})"
    desc = description.strip().splitlines()[0] if description else ""
    return f"- {name}{marker} — {desc}{state_marker}"


def build_catalog(workspace: Path | None = None, *, max_chars: int = 10_000) -> str:
    """Return a one-line-per-skill catalog suitable for system-prompt injection.

    Includes active and stale skills only. Pinned skills are listed first
    within the active section. Truncates at ``max_chars`` with an
    ``... and N more`` trailer.
    """
    catalog = discover_skills(workspace, include_archived=False)
    if not catalog:
        return ""

    active_pinned: list[tuple[str, str, str]] = []
    active_unpinned: list[tuple[str, str, str]] = []
    stale: list[tuple[str, str, str]] = []

    for name, (fm, _dir) in catalog.items():
        row = (name, fm.description, fm.state)
        if fm.state == "stale":
            stale.append(row)
        elif fm.pinned:
            active_pinned.append(row)
        else:
            active_unpinned.append(row)

    active_pinned.sort(key=lambda r: r[0])
    active_unpinned.sort(key=lambda r: r[0])
    stale.sort(key=lambda r: r[0])

    rows: list[str] = []
    for n, d, s in active_pinned:
        rows.append(_line(n, True, s, d))
    for n, d, s in active_unpinned:
        rows.append(_line(n, False, s, d))
    for n, d, s in stale:
        # Stale skills are never pinned (pinned skills can't go stale via the
        # state machine), so the pinned flag is always False here.
        rows.append(_line(n, False, s, d))

    body = _CATALOG_HEADER + "\n\n" + "\n".join(rows)
    if len(body) <= max_chars:
        return body

    # Walk back to the last full line that fits, then append the trailer.
    truncated_rows: list[str] = []
    running = len(_CATALOG_HEADER) + 2  # header + blank line
    reserved = len(_TRAILER) + len(str(len(rows)))
    for r in rows:
        if running + len(r) + 1 + reserved > max_chars:
            break
        truncated_rows.append(r)
        running += len(r) + 1

    leftover = len(rows) - len(truncated_rows)
    return _CATALOG_HEADER + "\n\n" + "\n".join(truncated_rows) + _TRAILER.format(n=leftover)
