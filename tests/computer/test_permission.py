"""Permission-gate tests (T6-04.1).

The most important tests in the entire computer-use phase. Each
encodes a load-bearing invariant from the design doc. They run
without any OS / backend / model — pure decision logic.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from athena.computer.contract import Action
from athena.computer.permission import PermissionGate


# ---------------------------------------------------------------------------
# Cfg helpers
# ---------------------------------------------------------------------------


def cfg(
    *,
    mode: str = "observe_only",
    allowlist: list[str] | None = None,
    denylist: list[str] | None = None,
) -> SimpleNamespace:
    """Tight cfg helper — defaults match the safest production
    config (observe_only, empty allowlist)."""
    return SimpleNamespace(
        computer_permission_mode=mode,
        computer_app_allowlist=allowlist or [],
        computer_app_denylist=denylist or [],
    )


def allow_all(a: Action, t) -> bool:
    return True


def deny_all(a: Action, t) -> bool:
    return False


# ---------------------------------------------------------------------------
# observe never asks
# ---------------------------------------------------------------------------


def test_observe_never_confirms():
    """A screenshot / observe action passes without prompting,
    even in the most restrictive mode."""
    gate = PermissionGate(cfg=cfg(mode="per_action"), confirm=deny_all)
    assert gate.check(Action(type="screenshot")) is True


def test_observe_passes_even_with_no_allowlist():
    """Observe-tier doesn't read the allowlist either — looking
    at the screen isn't gated by which app is foreground."""
    gate = PermissionGate(
        cfg=cfg(mode="observe_only", allowlist=[]), confirm=deny_all
    )
    assert gate.check(Action(type="screenshot")) is True


# ---------------------------------------------------------------------------
# denylist always wins
# ---------------------------------------------------------------------------


def test_denylist_wins_no_prompt():
    """A denylisted app is never controlled — and the gate doesn't
    even ask. No confirm callback fires."""
    asked: list = []

    def _watcher(a: Action, t) -> bool:
        asked.append((a, t))
        return True

    gate = PermissionGate(
        cfg=cfg(mode="per_session", allowlist=["bank"], denylist=["bank"]),
        confirm=_watcher,
    )
    allowed = gate.check(
        Action(type="click", target_desc="OK", app="bank.app")
    )
    assert allowed is False
    assert asked == []  # no prompt fired — denylist short-circuits


def test_denylist_wins_over_destructive_confirm_path():
    """Even a destructive action in a denylisted app gets refused
    without the user being asked. This is the worst-case
    interaction (model targets a denylisted app for a destructive
    action) — the gate must refuse silently, not confirm."""
    asked: list = []
    gate = PermissionGate(
        cfg=cfg(
            mode="per_action",
            allowlist=["everything"],
            denylist=["password"],
        ),
        confirm=lambda a, t: asked.append(t) or True,
    )
    allowed = gate.check(
        Action(
            type="click", target_desc="Delete account", app="password-manager"
        )
    )
    assert allowed is False
    assert asked == []


def test_denylist_partial_match_blocks():
    """The denylist matches substrings (case-insensitive) so a
    user blocking '1password' also blocks '1Password 7', etc."""
    gate = PermissionGate(
        cfg=cfg(
            mode="per_action",
            allowlist=["1Password 7"],
            denylist=["1password"],
        ),
        confirm=allow_all,
    )
    assert (
        gate.check(Action(type="click", target_desc="OK", app="1Password 7"))
        is False
    )


# ---------------------------------------------------------------------------
# allowlist gating
# ---------------------------------------------------------------------------


def test_not_in_allowlist_blocked():
    """Input requires an allowlisted app, period. Empty allowlist
    = no app is approved for control."""
    gate = PermissionGate(
        cfg=cfg(mode="per_action", allowlist=["editor"]),
        confirm=allow_all,
    )
    assert (
        gate.check(Action(type="click", target_desc="OK", app="browser"))
        is False
    )


def test_empty_allowlist_blocks_all_input():
    """The default empty allowlist is the safest possible state:
    even in per_action mode, no input passes because no app is
    approved for control."""
    gate = PermissionGate(
        cfg=cfg(mode="per_action", allowlist=[]), confirm=allow_all
    )
    assert (
        gate.check(Action(type="click", target_desc="OK", app="editor"))
        is False
    )


def test_no_app_name_blocked_under_allowlist():
    """An action whose app couldn't be detected can't satisfy
    the allowlist match — refuse. Conservative."""
    gate = PermissionGate(
        cfg=cfg(mode="per_action", allowlist=["editor"]),
        confirm=allow_all,
    )
    assert (
        gate.check(Action(type="click", target_desc="OK", app=None))
        is False
    )


def test_allowlist_substring_match():
    """The allowlist matches substrings (case-insensitive). An
    entry "code" matches "VS Code"; an entry "editor" matches
    "VS Code Editor" / "Sublime Editor" but does NOT match
    "TextEdit" (substring "editor" isn't in "TextEdit"). The
    substring semantics are documented; partial-match is
    convenient but tests pin the actual behaviour."""
    gate = PermissionGate(
        cfg=cfg(mode="per_action", allowlist=["editor"]),
        confirm=allow_all,
    )
    assert (
        gate.check(Action(type="click", target_desc="Tab 2", app="VS Code Editor"))
        is True
    )
    assert (
        gate.check(Action(type="click", target_desc="Tab 2", app="Sublime Editor"))
        is True
    )
    # And the strictly-shorter substring case — "code" matches
    # "VS Code".
    gate2 = PermissionGate(
        cfg=cfg(mode="per_action", allowlist=["code"]),
        confirm=allow_all,
    )
    assert (
        gate2.check(Action(type="click", target_desc="Tab 2", app="VS Code"))
        is True
    )
    # But "editor" does NOT match "TextEdit" — no substring.
    assert (
        gate.check(Action(type="click", target_desc="Tab 2", app="TextEdit"))
        is False
    )


# ---------------------------------------------------------------------------
# observe_only mode — the safe default
# ---------------------------------------------------------------------------


def test_observe_only_blocks_all_input():
    """In observe_only mode, EVERY input is refused without a
    prompt — even when the action would otherwise be plain
    `input` tier in an allowlisted app."""
    asked: list = []
    gate = PermissionGate(
        cfg=cfg(mode="observe_only", allowlist=["editor"]),
        confirm=lambda a, t: asked.append(t) or True,
    )
    assert (
        gate.check(
            Action(type="type", text="hi", target_desc="text field", app="editor")
        )
        is False
    )
    assert (
        gate.check(
            Action(type="click", target_desc="Tab 2", app="editor")
        )
        is False
    )
    # Confirm callback never invoked — observe_only short-
    # circuits before tier-specific branches.
    assert asked == []


def test_observe_only_still_allows_observe():
    """observe_only blocks input but not observe."""
    gate = PermissionGate(cfg=cfg(mode="observe_only"), confirm=deny_all)
    assert gate.check(Action(type="screenshot")) is True


# ---------------------------------------------------------------------------
# Destructive always confirms — EVERY mode
# ---------------------------------------------------------------------------


def test_destructive_always_confirms_per_action():
    asked: list = []
    gate = PermissionGate(
        cfg=cfg(mode="per_action", allowlist=["editor"]),
        confirm=lambda a, t: asked.append(t) or True,
    )
    gate.check(Action(type="click", target_desc="Delete", app="editor"))
    assert "destructive" in asked


def test_destructive_always_confirms_even_per_session():
    """The load-bearing invariant. per_session grants input
    control for the task, BUT destructive actions still confirm
    individually. This is what makes per_session safe to use."""
    asked: list = []
    gate = PermissionGate(
        cfg=cfg(mode="per_session", allowlist=["editor"]),
        confirm=lambda a, t: asked.append(t) or True,
    )
    # First input — grants the session.
    gate.check(Action(type="click", target_desc="OK", app="editor"))
    # Second input — covered by the session grant; no prompt.
    asked.clear()
    gate.check(Action(type="click", target_desc="Tab 2", app="editor"))
    assert asked == []
    # NOW the destructive one — must prompt despite the grant.
    gate.check(Action(type="click", target_desc="Delete row", app="editor"))
    assert asked == ["destructive"]


def test_destructive_in_observe_only_refuses_no_prompt():
    """observe_only is so restrictive that destructive doesn't
    even get to the confirm callback — the mode check fires first."""
    asked: list = []
    gate = PermissionGate(
        cfg=cfg(mode="observe_only", allowlist=["editor"]),
        confirm=lambda a, t: asked.append(t) or True,
    )
    allowed = gate.check(
        Action(type="click", target_desc="Delete", app="editor")
    )
    assert allowed is False
    assert asked == []


# ---------------------------------------------------------------------------
# Confirm-mode mechanics
# ---------------------------------------------------------------------------


def test_per_action_confirms_each_input():
    """In per_action mode each input action gets its own
    prompt — no session-wide grant."""
    asked: list = []
    gate = PermissionGate(
        cfg=cfg(mode="per_action", allowlist=["editor"]),
        confirm=lambda a, t: (asked.append(t) or True),
    )
    gate.check(Action(type="click", target_desc="Tab 1", app="editor"))
    gate.check(Action(type="click", target_desc="Tab 2", app="editor"))
    gate.check(Action(type="type", text="hi", target_desc="field", app="editor"))
    assert asked == ["input", "input", "input"]


def test_per_session_grants_input_once_but_not_destructive():
    """per_session asks for input once (granted), then no more
    input prompts; destructive still confirms each time."""
    prompts: list = []
    gate = PermissionGate(
        cfg=cfg(mode="per_session", allowlist=["editor"]),
        confirm=lambda a, t: (prompts.append(t) or True),
    )
    gate.check(Action(type="click", target_desc="OK", app="editor"))
    gate.check(Action(type="click", target_desc="Tab 2", app="editor"))
    gate.check(Action(type="type", text="hi", target_desc="field", app="editor"))
    gate.check(Action(type="click", target_desc="Save as", app="editor"))
    # ONE input prompt for the whole session...
    assert prompts.count("input") == 1
    # ...plus each destructive (none yet)
    assert "destructive" not in prompts
    # Now a destructive action — confirms individually.
    gate.check(Action(type="click", target_desc="Discard changes", app="editor"))
    assert prompts.count("destructive") == 1


def test_per_session_denial_persists():
    """If the user denies the session grant, subsequent inputs
    in the same session continue to be refused — without
    re-prompting until reset_session()."""
    asked: list = []
    gate = PermissionGate(
        cfg=cfg(mode="per_session", allowlist=["editor"]),
        confirm=lambda a, t: (asked.append(t) or False),
    )
    assert (
        gate.check(Action(type="click", target_desc="OK", app="editor"))
        is False
    )
    # Second input also refused, no new prompt.
    asked.clear()
    assert (
        gate.check(Action(type="click", target_desc="Tab 2", app="editor"))
        is False
    )
    assert asked == []


def test_reset_session_re_prompts():
    """reset_session() — called when the loop exits — forces the
    next per_session task to re-confirm input."""
    asked: list = []
    gate = PermissionGate(
        cfg=cfg(mode="per_session", allowlist=["editor"]),
        confirm=lambda a, t: (asked.append(t) or True),
    )
    gate.check(Action(type="click", target_desc="OK", app="editor"))
    assert asked == ["input"]
    gate.reset_session()
    asked.clear()
    gate.check(Action(type="click", target_desc="Tab 2", app="editor"))
    assert asked == ["input"]  # re-prompted


# ---------------------------------------------------------------------------
# Defensive behaviour
# ---------------------------------------------------------------------------


def test_unknown_mode_refuses():
    """A typo'd permission_mode treats as observe_only (refuse).
    Better than open-failing into an unknown branch."""
    gate = PermissionGate(
        cfg=cfg(mode="zarquon", allowlist=["editor"]),
        confirm=allow_all,
    )
    assert (
        gate.check(Action(type="click", target_desc="OK", app="editor"))
        is False
    )


def test_confirm_callback_raises_treated_as_denial():
    """A buggy confirm callback (UI crashed, user pressed
    escape, etc.) must NOT open-fail — the gate treats any
    raised exception as a denial."""

    def _explodes(a: Action, t) -> bool:
        raise RuntimeError("UI crashed")

    gate = PermissionGate(
        cfg=cfg(mode="per_action", allowlist=["editor"]),
        confirm=_explodes,
    )
    assert (
        gate.check(Action(type="click", target_desc="OK", app="editor"))
        is False
    )


def test_destructive_denial_blocks():
    """User says no to the destructive confirm → refused."""
    gate = PermissionGate(
        cfg=cfg(mode="per_action", allowlist=["editor"]),
        confirm=deny_all,
    )
    assert (
        gate.check(Action(type="click", target_desc="Delete", app="editor"))
        is False
    )


def test_destructive_approval_allows():
    gate = PermissionGate(
        cfg=cfg(mode="per_action", allowlist=["editor"]),
        confirm=allow_all,
    )
    assert (
        gate.check(Action(type="click", target_desc="Delete", app="editor"))
        is True
    )
