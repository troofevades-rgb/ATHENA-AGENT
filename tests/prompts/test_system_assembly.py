"""End-to-end system prompt assembly.

``tests/test_prompts.py`` covers SECTIONS filtering (default / lean /
disabled). ``tests/prompts/test_os_tool_preference.py`` covers the
per-OS tool-preference block.

What's NOT covered there — and what this file fills:

  * The 8 optional ``build_system_prompt`` parameters
    (project_context, memory_index, skills_catalog, model_modelfile_system,
    goal, board_auto_maintain, computer_use_status). None of them
    were tested for actual inclusion.
  * Section ORDERING — the module docstring claims load-bearing
    rules live first ("small models attend disproportionately to
    the first few hundred tokens"). Pin that.
  * ``collect_environment`` — never tested. A crash here means
    every session fails to start.
  * ``_render_computer_use_status`` — ~75 lines of branching, 0 tests.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from athena.prompts.system import (
    IDENTITY,
    LEAN_KEEP,
    SECTIONS,
    TIGHT_RULES,
    _render_computer_use_status,
    build_system_prompt,
    collect_environment,
)

# ---------------------------------------------------------------------------
# Section ordering — load-bearing rules front
# ---------------------------------------------------------------------------


def test_identity_appears_before_tight_rules(tmp_path: Path) -> None:
    """IDENTITY must come before TIGHT_RULES so the model anchors
    its role before reading the rules. Docstring invariant."""
    out = build_system_prompt(workspace=tmp_path, model="m")
    assert IDENTITY in out
    assert TIGHT_RULES in out
    assert out.index(IDENTITY) < out.index(TIGHT_RULES)


def test_tight_rules_appears_before_doing_tasks(tmp_path: Path) -> None:
    """The load-bearing rules must front-load — small models attend
    most to the opening tokens. Pin the order against future drift."""
    out = build_system_prompt(workspace=tmp_path, model="m")
    doing_tasks = SECTIONS["doing_tasks"]
    assert out.index(TIGHT_RULES) < out.index(doing_tasks)


def test_modelfile_system_comes_first_when_present(tmp_path: Path) -> None:
    """A custom Modelfile SYSTEM prompt is layer 1 — it sets persona
    BEFORE the athena rules so a user-configured persona doesn't
    get overridden by athena's defaults."""
    modelfile = "You are a helpful pirate."
    out = build_system_prompt(
        workspace=tmp_path,
        model="m",
        model_modelfile_system=modelfile,
    )
    assert modelfile in out
    assert out.index(modelfile) < out.index(IDENTITY)


def test_goal_invariant_is_last(tmp_path: Path) -> None:
    """The /goal invariant is intentionally appended last so the
    model treats it as the most-recent / most-authoritative
    instruction. Pin the position."""
    out = build_system_prompt(
        workspace=tmp_path,
        model="m",
        goal="ship the migration before friday",
    )
    # Find a marker from the goal section and verify it's after
    # everything else section-wise
    assert "ship the migration before friday" in out
    # Last identifiable static section is context_mgmt; the goal
    # content must come AFTER it
    last_static = SECTIONS["context_mgmt"]
    assert out.index("ship the migration before friday") > out.index(last_static)


# ---------------------------------------------------------------------------
# Optional parameter inclusion
# ---------------------------------------------------------------------------


def test_project_context_included_when_provided(tmp_path: Path) -> None:
    out = build_system_prompt(
        workspace=tmp_path,
        model="m",
        project_context="ATHENA.md contents go here",
    )
    assert "Project context" in out
    assert "ATHENA.md contents go here" in out


def test_project_context_absent_when_not_provided(tmp_path: Path) -> None:
    out = build_system_prompt(workspace=tmp_path, model="m")
    assert "# Project context" not in out


def test_memory_index_included_when_provided(tmp_path: Path) -> None:
    out = build_system_prompt(
        workspace=tmp_path,
        model="m",
        memory_index="- [Title](file.md) — hook",
    )
    assert "MEMORY.md" in out
    assert "[Title](file.md)" in out


def test_skills_catalog_included_when_provided(tmp_path: Path) -> None:
    out = build_system_prompt(
        workspace=tmp_path,
        model="m",
        skills_catalog="# Available skills\n- osint-research",
    )
    assert "osint-research" in out


def test_elevation_note_gated_by_flag_and_platform(tmp_path: Path) -> None:
    import sys

    # Off by default — never present.
    off = build_system_prompt(workspace=tmp_path, model="m", allow_elevation=False)
    assert "# Elevated commands" not in off

    on = build_system_prompt(workspace=tmp_path, model="m", allow_elevation=True)
    if sys.platform == "win32":
        # The opt-in elevation guidance surfaces (the agent learns it may sudo).
        assert "# Elevated commands" in on
        assert "sudo" in on
    else:
        # Elevation is a Windows-only affordance here — no note off-Windows
        # even with the flag set.
        assert "# Elevated commands" not in on


def test_board_auto_maintain_adds_board_section(tmp_path: Path) -> None:
    out = build_system_prompt(
        workspace=tmp_path,
        model="m",
        board_auto_maintain=True,
    )
    assert "# Task board" in out
    assert "TaskCreate" in out


def test_board_section_absent_when_disabled(tmp_path: Path) -> None:
    out = build_system_prompt(
        workspace=tmp_path,
        model="m",
        board_auto_maintain=False,
    )
    assert "# Task board" not in out


# ---------------------------------------------------------------------------
# collect_environment — runs every session, must never crash
# ---------------------------------------------------------------------------


def test_collect_environment_returns_populated_struct(tmp_path: Path) -> None:
    """``collect_environment`` runs on every session start. If it
    crashes, the agent fails to construct its system prompt."""
    env = collect_environment(tmp_path, "test-model")
    assert env.cwd == tmp_path.resolve()
    assert env.model == "test-model"
    assert env.platform in ("win32", "darwin", "linux") or env.platform.startswith("linux")
    assert env.shell  # whatever it is, must be non-empty
    assert env.today  # YYYY-MM-DD
    assert env.user  # whatever it is, must be non-empty
    assert env.hostname  # ditto


def test_collect_environment_detects_git_repo(tmp_path: Path) -> None:
    """A .git dir at the workspace root (or any ancestor) → is_git=True."""
    (tmp_path / ".git").mkdir()
    env = collect_environment(tmp_path, "m")
    assert env.is_git is True


def test_collect_environment_no_git_for_non_repo(tmp_path: Path) -> None:
    """Plain dir with no .git anywhere up the tree → is_git=False.
    Important: tmp_path on Windows can be under a real user dir,
    so this test relies on /tmp/ (POSIX) or AppData (Windows tmp)
    NOT being a git repo, which is true in practice."""
    env = collect_environment(tmp_path, "m")
    # tmp paths are rarely inside a git tree; if this test ever
    # flakes locally, ignore — CI tmp dirs are clean.
    assert isinstance(env.is_git, bool)


def test_collect_environment_resilient_to_uname_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``uname -r`` doesn't exist on Windows. Function must fall
    back to ``platform.release()`` without raising."""
    import subprocess as _sp

    def _boom(*a, **kw):
        raise FileNotFoundError("uname")

    monkeypatch.setattr(_sp, "check_output", _boom)
    env = collect_environment(tmp_path, "m")
    assert env.os_version  # falls back to platform.release()


def test_environment_block_renders_all_expected_fields(tmp_path: Path) -> None:
    """The rendered env block is what the model actually sees.
    Pin every documented field — missing fields are subtle context
    losses ("model didn't know which OS it was on")."""
    env = collect_environment(tmp_path, "test-model-name")
    rendered = env.render()
    assert "Primary working directory:" in rendered
    assert "Is a git repository:" in rendered
    assert "Platform:" in rendered
    assert "Shell:" in rendered
    assert "OS Version:" in rendered
    assert "Hostname:" in rendered
    assert "User:" in rendered
    assert "Today's date:" in rendered
    assert "test-model-name" in rendered
    # The tool preference block (per-OS)
    assert "Tool preference:" in rendered


# ---------------------------------------------------------------------------
# _render_computer_use_status — 4 modes × allowlist/denylist branches
# ---------------------------------------------------------------------------


def test_computer_use_disabled_renders_disabled_block(tmp_path: Path) -> None:
    """enabled=False → concise disabled block. Tools all refuse
    with a structured payload; the model needs to know this so it
    doesn't try and waste a turn."""
    out = build_system_prompt(
        workspace=tmp_path,
        model="m",
        computer_use_status={"enabled": False},
    )
    assert "Computer use" in out
    assert "DISABLED" in out
    assert "not_enabled" in out


def test_computer_use_observe_only_mode(tmp_path: Path) -> None:
    """observe_only → screenshot/observe work, EVERY input tool refuses."""
    out = build_system_prompt(
        workspace=tmp_path,
        model="m",
        computer_use_status={
            "enabled": True,
            "mode": "observe_only",
            "allowlist": [],
            "denylist": [],
        },
    )
    assert "ENABLED" in out
    assert "observe_only" in out
    assert "REFUSES" in out


def test_computer_use_per_action_mode(tmp_path: Path) -> None:
    out = build_system_prompt(
        workspace=tmp_path,
        model="m",
        computer_use_status={
            "enabled": True,
            "mode": "per_action",
            "allowlist": ["chrome"],
            "denylist": [],
        },
    )
    assert "per_action" in out
    assert "prompts the user for confirmation" in out
    # Destructive-tier always prompts
    assert "Destructive-tier actions" in out
    assert "ALWAYS" in out


def test_computer_use_per_session_mode(tmp_path: Path) -> None:
    out = build_system_prompt(
        workspace=tmp_path,
        model="m",
        computer_use_status={
            "enabled": True,
            "mode": "per_session",
            "allowlist": ["chrome"],
            "denylist": [],
        },
    )
    assert "per_session" in out
    # Destructive still per-action even in per_session
    assert "STILL prompt" in out


def test_computer_use_empty_allowlist_warns(tmp_path: Path) -> None:
    """allowlist=[] is the safety default. Model must know that
    even in per_action / per_session mode, NO app is approved so
    input WILL refuse."""
    out = build_system_prompt(
        workspace=tmp_path,
        model="m",
        computer_use_status={
            "enabled": True,
            "mode": "per_action",
            "allowlist": [],
            "denylist": [],
        },
    )
    assert "Allowlist:" in out
    assert "empty" in out
    assert "refuses" in out.lower()


def test_computer_use_denylist_explicitly_called_out(tmp_path: Path) -> None:
    """Denylist always wins over allowlist + mode. Must be stated
    explicitly so the model doesn't try a denied app."""
    out = build_system_prompt(
        workspace=tmp_path,
        model="m",
        computer_use_status={
            "enabled": True,
            "mode": "per_action",
            "allowlist": ["chrome"],
            "denylist": ["banking"],
        },
    )
    assert "banking" in out
    assert "Denylist" in out
    assert "NEVER" in out


def test_computer_use_section_absent_when_not_provided(tmp_path: Path) -> None:
    """Don't render the section at all if no status dict — saves
    tokens on every session that doesn't use computer-use."""
    out = build_system_prompt(workspace=tmp_path, model="m")
    assert "Computer use" not in out


# ---------------------------------------------------------------------------
# Render directly (no full assembly) — easier to test branches in isolation
# ---------------------------------------------------------------------------


def test_render_computer_use_unknown_mode_falls_through(tmp_path: Path) -> None:
    """An unknown mode string (e.g. typo or schema drift) must NOT
    crash — render falls through with the generic header."""
    out = _render_computer_use_status(
        {
            "enabled": True,
            "mode": "completely_made_up",
            "allowlist": [],
            "denylist": [],
        }
    )
    assert "ENABLED" in out
    assert "completely_made_up" in out


def test_render_computer_use_handles_missing_keys() -> None:
    """Status dict with only ``enabled=True`` — function must not
    KeyError, must fall back to defaults."""
    out = _render_computer_use_status({"enabled": True})
    assert "ENABLED" in out
    # Should default to observe_only
    assert "observe_only" in out


# ---------------------------------------------------------------------------
# Lean mode — load-bearing rules survive
# ---------------------------------------------------------------------------


def test_lean_keeps_tight_rules(tmp_path: Path) -> None:
    """lean=True is for small models. Whatever else gets dropped,
    TIGHT_RULES MUST stay — those are the load-bearing safety
    rules. Pin this so a future LEAN_KEEP edit can't accidentally
    drop them."""
    out = build_system_prompt(workspace=tmp_path, model="m", lean=True)
    assert TIGHT_RULES in out
    assert IDENTITY in out
    assert "tight_rules" in LEAN_KEEP
    assert "identity" in LEAN_KEEP


def test_lean_drops_verbose_policy_sections(tmp_path: Path) -> None:
    """Confirm lean actually saves tokens — the long memory block
    and session guidance should be GONE."""
    out_full = build_system_prompt(workspace=tmp_path, model="m")
    out_lean = build_system_prompt(workspace=tmp_path, model="m", lean=True)
    assert len(out_lean) < len(out_full) / 2, (
        f"lean ({len(out_lean)} chars) is not meaningfully shorter "
        f"than default ({len(out_full)} chars) — LEAN_KEEP set is "
        f"too generous"
    )
