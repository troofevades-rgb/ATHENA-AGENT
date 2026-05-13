"""Summarize the result of a background-review fork.

The fork's ``ForkResult.actions`` is a list of :class:`ForkAction` records
extracted from the structured tool responses (skill_manage, write_memory).
We bucket them into ``memory_writes`` and ``skill_changes`` so the parent
agent can show a one-line acknowledgment on the next prompt.
"""
from __future__ import annotations

from typing import Any


_SKILL_TARGETS = {"skill"}
_MEMORY_TARGETS = {"memory"}


def extract_summary(fork_result: Any) -> dict:
    """Bucket ``fork_result.actions`` into per-target lists.

    Returns ``{"memory_writes": [...], "skill_changes": [...]}``. Each list
    entry is a small dict ``{"name": ..., "action": ..., "detail": ...}`` so
    the caller can render it however it wants.
    """
    memory_writes: list[dict[str, Any]] = []
    skill_changes: list[dict[str, Any]] = []
    actions = getattr(fork_result, "actions", []) or []
    for a in actions:
        entry = {"name": a.name, "action": a.action, "detail": a.detail}
        if a.target in _MEMORY_TARGETS:
            memory_writes.append(entry)
        elif a.target in _SKILL_TARGETS:
            skill_changes.append(entry)
    return {"memory_writes": memory_writes, "skill_changes": skill_changes}


def format_for_user(summary: dict) -> str:
    """One-line acknowledgment string. Empty string when nothing happened."""
    mem = summary.get("memory_writes") or []
    skl = summary.get("skill_changes") or []
    if not mem and not skl:
        return ""

    parts: list[str] = []
    if mem:
        word = "entry" if len(mem) == 1 else "entries"
        parts.append(f"{len(mem)} memory {word}")
    if skl:
        word = "skill" if len(skl) == 1 else "skills"
        parts.append(f"{len(skl)} {word} touched")
    return "Background review: " + ", ".join(parts) + "."
