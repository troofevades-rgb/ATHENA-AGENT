"""Tests for the per-turn review prompt texts.

These are intentionally loose — we don't pin exact wording, but we lock in
the load-bearing phrases the architecture depends on (anti-capture list,
umbrella preference) so a future edit can't silently drop them.
"""
from __future__ import annotations

from ocode.review.prompts import COMBINED, MEMORY_REVIEW, SKILL_REVIEW


def test_combined_includes_memory_and_skill_blocks() -> None:
    assert MEMORY_REVIEW in COMBINED
    assert SKILL_REVIEW in COMBINED


def test_combined_includes_anti_capture_list() -> None:
    assert "Anti-capture list" in COMBINED
    # Specific anti-bias phrases that the architecture relies on:
    assert "frustration is a first-class signal" in COMBINED.lower() or \
           "Frustration" in COMBINED
    assert "the-thing-we-just-did-once" in COMBINED


def test_combined_includes_umbrella_preference_text() -> None:
    assert "Umbrella preference" in COMBINED
    # Mentions patching before creating
    lower = COMBINED.lower()
    assert "patch" in lower and "create" in lower


def test_combined_warns_against_hardening_transient_errors() -> None:
    """One of the most important anti-bias instructions — drop it and the
    review will start writing 'X is broken' memories from one-off failures."""
    assert "Transient errors" in COMBINED or "transient errors" in COMBINED
    assert "do NOT harden" in COMBINED or "do not harden" in COMBINED.lower()


def test_class_level_naming_guidance_present() -> None:
    assert "class-level" in COMBINED.lower()


def test_tools_lists_are_explicit() -> None:
    """Each block must enumerate the tools available so the model doesn't
    invent unsupported actions."""
    assert "skills_list" in SKILL_REVIEW
    assert "skill_view" in SKILL_REVIEW
    assert "skill_manage" in SKILL_REVIEW
    assert "write_memory" in MEMORY_REVIEW
    assert "list_memories" in MEMORY_REVIEW
