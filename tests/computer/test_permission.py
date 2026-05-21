"""Permission-gate tests (T6-04, refactored for T6-04R).

The most important tests in the entire computer-use phase. Each
encodes a load-bearing invariant from the design doc. They run
without any OS / backend / model — pure decision logic.

T6-04R refactor: the gate no longer takes a bespoke ``confirm``
callback. Approval routes through
:mod:`athena.safety.approval_guard` + the active
:mod:`athena.safety.approval_callback`. Tests bind a recording
callback via :func:`set_approval_callback` and assert what was
asked.

Semantic change worth noting: with T6-04R, the input tier
ALWAYS caches per turn (via approval_guard's ContextVar grant
dict). The legacy ``per_action`` vs ``per_session`` mode
distinction is preserved at the config level but no longer
controls input caching — both modes cache via the same
approval_guard ``computer_input`` key. The tier-specific
caching policy is now: input caches; destructive never does
(per-action resource_id includes a hash of the action
description). See ``tests/computer/test_gate_tiers.py`` for the
direct pin.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from athena.computer.contract import Action
from athena.computer.permission import PermissionGate
from athena.safety.approval_callback import (
    reset_approval_callback,
    set_approval_callback,
)
from athena.safety.approval_guard import (
    clear_grants,
    current_grants,
)


# ---------------------------------------------------------------------------
# Cfg + callback helpers
# ---------------------------------------------------------------------------


def cfg(
    *,
    mode: str = "observe_only",
    allowlist: list[str] | None = None,
    denylist: list[str] | None = None,
    deny_during_goal_loop: bool = False,
) -> SimpleNamespace:
    """Tight cfg helper — defaults match the safest production
    config (observe_only, empty allowlist). Goal-loop deny is
    OFF by default in these tests because the legacy invariants
    target the bare-gate behavior; the goal-loop interaction is
    tested separately in test_gate_tiers.py."""
    return SimpleNamespace(
        computer_permission_mode=mode,
        computer_app_allowlist=allowlist or [],
        computer_app_denylist=denylist or [],
        computer_deny_during_goal_loop=deny_during_goal_loop,
        profile="default",
    )


def _bind(verdict_for=lambda action, tier: True):
    """Install an approval callback that records every prompt and
    returns "allow"/"deny" based on ``verdict_for(action, tier)``.

    Returns ``(token, asks)`` — caller passes ``token`` to
    :func:`reset_approval_callback` in teardown and reads
    ``asks`` (list of tier strings, in prompt order) to verify
    the gate's behavior.

    The legacy tests recorded the *tier* string; we keep that
    shape so the asserts in this file stay readable.
    """
    asks: list[str] = []

    def _cb(tool_name: str, args: dict) -> str:
        tier = args.get("tier", "?")
        asks.append(tier)
        # Tests pass a function returning bool; the gate sees
        # "allow" or "deny".
        try:
            ok = bool(verdict_for(args, tier))
        except Exception:
            ok = False
        return "allow" if ok else "deny"

    token = set_approval_callback(_cb)
    return token, asks


@pytest.fixture(autouse=True)
def _fresh_grants():
    """Drop approval grants between tests so a cached grant
    from one test can't bleed into another (the new design's
    cache is the ContextVar, not gate state)."""
    clear_grants()
    yield
    clear_grants()


# ---------------------------------------------------------------------------
# observe never asks
# ---------------------------------------------------------------------------


def test_observe_never_confirms():
    """A screenshot / observe action passes without prompting,
    even in the most restrictive mode."""
    gate = PermissionGate(cfg=cfg(mode="per_action"))
    token, asks = _bind(lambda a, t: False)
    try:
        assert gate.check(Action(type="screenshot")) is True
        assert asks == []
    finally:
        reset_approval_callback(token)


def test_observe_passes_even_with_no_allowlist():
    """Observe-tier doesn't read the allowlist either — looking
    at the screen isn't gated by which app is foreground."""
    gate = PermissionGate(cfg=cfg(mode="observe_only", allowlist=[]))
    token, asks = _bind(lambda a, t: False)
    try:
        assert gate.check(Action(type="screenshot")) is True
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------------------
# denylist always wins
# ---------------------------------------------------------------------------


def test_denylist_wins_no_prompt():
    gate = PermissionGate(
        cfg=cfg(mode="per_session", allowlist=["bank"], denylist=["bank"])
    )
    token, asks = _bind(lambda a, t: True)
    try:
        assert (
            gate.check(Action(type="click", target_desc="OK", app="bank.app"))
            is False
        )
        assert asks == []
    finally:
        reset_approval_callback(token)


def test_denylist_wins_over_destructive_confirm_path():
    """Even a destructive action in a denylisted app is refused
    without the user being asked."""
    gate = PermissionGate(
        cfg=cfg(
            mode="per_action",
            allowlist=["everything"],
            denylist=["password"],
        ),
    )
    token, asks = _bind(lambda a, t: True)
    try:
        assert (
            gate.check(
                Action(
                    type="click", target_desc="Delete account",
                    app="password-manager",
                )
            )
            is False
        )
        assert asks == []
    finally:
        reset_approval_callback(token)


def test_denylist_partial_match_blocks():
    gate = PermissionGate(
        cfg=cfg(
            mode="per_action",
            allowlist=["1Password 7"],
            denylist=["1password"],
        ),
    )
    token, _ = _bind(lambda a, t: True)
    try:
        assert (
            gate.check(Action(type="click", target_desc="OK", app="1Password 7"))
            is False
        )
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------------------
# allowlist gating
# ---------------------------------------------------------------------------


def test_not_in_allowlist_blocked():
    gate = PermissionGate(cfg=cfg(mode="per_action", allowlist=["editor"]))
    token, _ = _bind(lambda a, t: True)
    try:
        assert (
            gate.check(Action(type="click", target_desc="OK", app="Slack"))
            is False
        )
    finally:
        reset_approval_callback(token)


def test_empty_allowlist_blocks_all_input():
    gate = PermissionGate(cfg=cfg(mode="per_action", allowlist=[]))
    token, _ = _bind(lambda a, t: True)
    try:
        assert (
            gate.check(Action(type="click", target_desc="OK", app="editor"))
            is False
        )
    finally:
        reset_approval_callback(token)


def test_no_app_name_blocked_under_allowlist():
    """No app name reported (a11y tree was silent) → can't match
    any allowlist entry → refuse. Conservative."""
    gate = PermissionGate(cfg=cfg(mode="per_action", allowlist=["editor"]))
    token, _ = _bind(lambda a, t: True)
    try:
        assert (
            gate.check(Action(type="click", target_desc="OK", app=None))
            is False
        )
    finally:
        reset_approval_callback(token)


def test_allowlist_substring_match():
    gate = PermissionGate(cfg=cfg(mode="per_action", allowlist=["editor"]))
    gate2 = PermissionGate(cfg=cfg(mode="per_action", allowlist=["VS Code"]))
    t1, _ = _bind(lambda a, t: True)
    try:
        # "editor" is not a substring of "VS Code" — refuse.
        assert (
            gate.check(Action(type="click", target_desc="Tab 2", app="VS Code"))
            is False
        )
    finally:
        reset_approval_callback(t1)
    t2, _ = _bind(lambda a, t: True)
    try:
        assert (
            gate2.check(Action(type="click", target_desc="Tab 2", app="VS Code"))
            is True
        )
    finally:
        reset_approval_callback(t2)
    t3, _ = _bind(lambda a, t: True)
    try:
        assert (
            gate.check(Action(type="click", target_desc="Tab 2", app="TextEdit"))
            is False
        )
    finally:
        reset_approval_callback(t3)


# ---------------------------------------------------------------------------
# observe_only mode — the safe default
# ---------------------------------------------------------------------------


def test_observe_only_blocks_all_input():
    gate = PermissionGate(
        cfg=cfg(mode="observe_only", allowlist=["editor"]),
    )
    token, asks = _bind(lambda a, t: True)
    try:
        assert (
            gate.check(
                Action(type="type", text="hi", target_desc="text field", app="editor")
            )
            is False
        )
        assert (
            gate.check(Action(type="click", target_desc="Tab 2", app="editor"))
            is False
        )
        # No prompts burned — observe_only short-circuits.
        assert asks == []
    finally:
        reset_approval_callback(token)


def test_observe_only_still_allows_observe():
    gate = PermissionGate(cfg=cfg(mode="observe_only"))
    token, _ = _bind(lambda a, t: False)
    try:
        assert gate.check(Action(type="screenshot")) is True
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------------------
# Destructive always confirms in any non-restrictive mode
# ---------------------------------------------------------------------------


def test_destructive_always_confirms_per_action():
    gate = PermissionGate(cfg=cfg(mode="per_action", allowlist=["editor"]))
    token, asks = _bind(lambda a, t: True)
    try:
        gate.check(Action(type="click", target_desc="Delete", app="editor"))
        assert "destructive" in asks
    finally:
        reset_approval_callback(token)


def test_destructive_always_confirms_even_per_session():
    """T6-04R behavior: per_session is essentially equivalent to
    per_action now (input always caches via approval_guard); but
    DESTRUCTIVE still freshly prompts every time — the cache key
    encodes the action so it never hits."""
    gate = PermissionGate(cfg=cfg(mode="per_session", allowlist=["editor"]))
    token, asks = _bind(lambda a, t: True)
    try:
        # First input — prompts and caches.
        gate.check(Action(type="click", target_desc="OK", app="editor"))
        # Second input — cached, no new prompt.
        asks.clear()
        gate.check(Action(type="click", target_desc="Tab 2", app="editor"))
        assert asks == []
        # Destructive — must prompt despite the cached input grant.
        gate.check(Action(type="click", target_desc="Delete row", app="editor"))
        assert asks == ["destructive"]
    finally:
        reset_approval_callback(token)


def test_destructive_in_observe_only_refuses_no_prompt():
    gate = PermissionGate(
        cfg=cfg(mode="observe_only", allowlist=["editor"]),
    )
    token, asks = _bind(lambda a, t: True)
    try:
        assert (
            gate.check(Action(type="click", target_desc="Delete", app="editor"))
            is False
        )
        assert asks == []
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------------------
# Caching mechanics — T6-04R semantics
# ---------------------------------------------------------------------------


def test_input_caches_after_first_grant():
    """T6-04R: every mode caches input grants via approval_guard's
    ContextVar. The legacy per_action / per_session distinction
    no longer drives input caching — both behave like per_session
    used to."""
    gate = PermissionGate(cfg=cfg(mode="per_action", allowlist=["editor"]))
    token, asks = _bind(lambda a, t: True)
    try:
        gate.check(Action(type="click", target_desc="Tab 1", app="editor"))
        gate.check(Action(type="click", target_desc="Tab 2", app="editor"))
        gate.check(Action(type="type", text="hi", target_desc="field", app="editor"))
        # Only one prompt — the rest hit the cached "computer_input" grant.
        assert asks == ["input"]
        assert "computer_input" in current_grants()
    finally:
        reset_approval_callback(token)


def test_per_session_input_grant_and_destructive_distinction():
    gate = PermissionGate(cfg=cfg(mode="per_session", allowlist=["editor"]))
    token, prompts = _bind(lambda a, t: True)
    try:
        gate.check(Action(type="click", target_desc="OK", app="editor"))
        gate.check(Action(type="click", target_desc="Tab 2", app="editor"))
        gate.check(Action(type="type", text="hi", target_desc="field", app="editor"))
        gate.check(Action(type="click", target_desc="Save as", app="editor"))
        assert prompts.count("input") == 1
        assert "destructive" not in prompts
        gate.check(Action(type="click", target_desc="Discard changes", app="editor"))
        assert prompts.count("destructive") == 1
    finally:
        reset_approval_callback(token)


def test_input_denial_persists_across_calls():
    """A denied input grant persists — the user isn't re-prompted
    until reset_session()."""
    gate = PermissionGate(cfg=cfg(mode="per_session", allowlist=["editor"]))
    token, asks = _bind(lambda a, t: False)
    try:
        assert (
            gate.check(Action(type="click", target_desc="OK", app="editor"))
            is False
        )
        asks.clear()
        assert (
            gate.check(Action(type="click", target_desc="Tab 2", app="editor"))
            is False
        )
        assert asks == []
    finally:
        reset_approval_callback(token)


def test_reset_session_re_prompts():
    """reset_session() — called when the loop exits — forces the
    next task to re-confirm input."""
    gate = PermissionGate(cfg=cfg(mode="per_session", allowlist=["editor"]))
    token, asks = _bind(lambda a, t: True)
    try:
        gate.check(Action(type="click", target_desc="OK", app="editor"))
        assert asks == ["input"]
        gate.reset_session()
        asks.clear()
        gate.check(Action(type="click", target_desc="Tab 2", app="editor"))
        assert asks == ["input"]
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------------------
# Defensive behaviour
# ---------------------------------------------------------------------------


def test_unknown_mode_refuses():
    """A typo'd permission_mode treats as observe_only (refuse) —
    open-failing into an unrecognised branch would be unsafe."""
    gate = PermissionGate(cfg=cfg(mode="zarquon", allowlist=["editor"]))
    token, _ = _bind(lambda a, t: True)
    try:
        assert (
            gate.check(Action(type="click", target_desc="OK", app="editor"))
            is False
        )
    finally:
        reset_approval_callback(token)


def test_confirm_callback_raises_treated_as_denial():
    """A buggy approval callback (UI crashed, etc.) must NOT
    open-fail — any raised exception is treated as denial."""
    gate = PermissionGate(cfg=cfg(mode="per_action", allowlist=["editor"]))

    def _explodes(tool_name: str, args: dict) -> str:
        raise RuntimeError("UI crashed")

    token = set_approval_callback(_explodes)
    try:
        assert (
            gate.check(Action(type="click", target_desc="OK", app="editor"))
            is False
        )
    finally:
        reset_approval_callback(token)


def test_destructive_denial_blocks():
    gate = PermissionGate(cfg=cfg(mode="per_action", allowlist=["editor"]))
    token, _ = _bind(lambda a, t: False)
    try:
        assert (
            gate.check(Action(type="click", target_desc="Delete", app="editor"))
            is False
        )
    finally:
        reset_approval_callback(token)


def test_destructive_approval_allows():
    gate = PermissionGate(cfg=cfg(mode="per_action", allowlist=["editor"]))
    token, _ = _bind(lambda a, t: True)
    try:
        assert (
            gate.check(Action(type="click", target_desc="Delete", app="editor"))
            is True
        )
    finally:
        reset_approval_callback(token)
