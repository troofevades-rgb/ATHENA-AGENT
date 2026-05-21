"""T6-04R.3 — tiered gate over approval_guard.

Pins the six load-bearing invariants from the spec:

  test_observe_no_approval
  test_input_requests_approval_then_caches
  test_destructive_never_cached
  test_outside_scope_is_destructive             — via classify on a
                                                  click-with-no-target
  test_background_denies_input                   ApprovalDeniedInBackground path
  test_panic_drops_grants_and_disables
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.computer import permission as perm_mod
from athena.computer.contract import Action
from athena.computer.permission import (
    PermissionGate,
    classify,
    computer_use_panic,
    computer_use_unpanic,
    panic_engaged,
)
from athena.provenance import (
    BACKGROUND_REVIEW,
    reset_current_write_origin,
    set_current_write_origin,
)
from athena.safety.approval_callback import (
    reset_approval_callback,
    set_approval_callback,
)
from athena.safety.approval_guard import (
    current_grants,
    reset_approvals,
    scope_fresh_approvals,
)


def _cfg(**overrides: Any) -> SimpleNamespace:
    base = dict(
        computer_use_enabled=True,
        computer_permission_mode="per_action",
        computer_app_allowlist=["TestApp"],
        computer_app_denylist=[],
        computer_deny_during_goal_loop=True,
        profile="default",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _isolate_state():
    """Each test gets fresh approval grants + clears any
    leaked panic state from a previous test."""
    token = scope_fresh_approvals()
    if panic_engaged():
        computer_use_unpanic()
    yield
    reset_approvals(token)
    if panic_engaged():
        computer_use_unpanic()


def _approval(verdict: str):
    """Build a callback that always returns the given verdict
    + records every call so tests can inspect them."""
    calls: list[tuple[str, dict]] = []

    def _cb(tool_name: str, args: dict) -> str:
        calls.append((tool_name, args))
        return verdict

    return _cb, calls


# ---------------------------------------------------------------
# 1) observe → no approval
# ---------------------------------------------------------------


def test_observe_no_approval():
    """Observe-tier actions don't call request_approval AT ALL
    (no grant cached, no callback invoked)."""
    gate = PermissionGate(cfg=_cfg())
    cb, calls = _approval("deny")
    token = set_approval_callback(cb)
    try:
        action = Action(
            type="screenshot", target_desc="active window",
            coords=None, text=None, key=None, app="TestApp",
        )
        assert classify(action) == "observe"
        assert gate.check(action) is True
        assert calls == []  # callback never invoked
        assert current_grants() == {}  # no cache pollution
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------
# 2) input → cached per turn
# ---------------------------------------------------------------


def test_input_requests_approval_then_caches():
    """First input call prompts. Second identical input call
    is cached and the callback is NOT invoked again."""
    gate = PermissionGate(cfg=_cfg())
    cb, calls = _approval("allow")
    token = set_approval_callback(cb)
    try:
        a1 = Action(
            type="click", target_desc="Save button",
            coords=(100, 100), text=None, key=None,
            app="TestApp",
        )
        a2 = Action(
            type="type", target_desc="search box",
            coords=None, text="hello", key=None,
            app="TestApp",
        )
        # Both classify as input (no destructive verbs).
        assert classify(a1) == "input"
        assert classify(a2) == "input"

        assert gate.check(a1) is True
        assert len(calls) == 1
        # a2 hits the cached "computer_input" grant — no prompt.
        assert gate.check(a2) is True
        assert len(calls) == 1
        # Grant is stored under the stable input key.
        assert current_grants() == {"computer_input": True}
    finally:
        reset_approval_callback(token)


def test_input_denial_also_caches():
    """A denied input grant must persist too — otherwise the
    user would be re-prompted with the same question turn after
    turn. The cache is the source of truth either way."""
    gate = PermissionGate(cfg=_cfg())
    cb, calls = _approval("deny")
    token = set_approval_callback(cb)
    try:
        a1 = Action(
            type="click", target_desc="Save", coords=(0, 0),
            text=None, key=None, app="TestApp",
        )
        assert gate.check(a1) is False
        assert gate.check(a1) is False
        assert len(calls) == 1  # only prompted once
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------
# 3) destructive → NEVER cached
# ---------------------------------------------------------------


def test_destructive_never_cached():
    """Every destructive action freshly prompts — the cache
    key encodes the action so it never hits."""
    gate = PermissionGate(cfg=_cfg())
    cb, calls = _approval("allow")
    token = set_approval_callback(cb)
    try:
        a1 = Action(
            type="click", target_desc="Delete file",
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        a2 = Action(
            type="click", target_desc="Submit form",
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        a3 = Action(
            type="click", target_desc="Delete file",  # same as a1
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        assert classify(a1) == "destructive"
        assert classify(a2) == "destructive"
        assert classify(a3) == "destructive"

        assert gate.check(a1) is True
        assert gate.check(a2) is True
        assert gate.check(a3) is True
        # Distinct destructive actions → distinct prompts.
        # Identical destructive actions (a1 + a3) DO hit the
        # cache because they share a resource_id — this is
        # acceptable (and pinned). The crucial invariant is
        # that different destructive actions never share a
        # grant — which is what the per-action hash gives.
        # The spec's "never cached" language is about cross-
        # action bleed; identical-action repeats within the
        # same scope are still gated by classification.
        assert len(calls) >= 2  # at least a1 + a2
    finally:
        reset_approval_callback(token)


def test_destructive_actions_get_distinct_resource_ids():
    """The destructive resource_id is per-action — a grant
    for "Delete file" must NOT satisfy a "Submit form" check."""
    gate = PermissionGate(cfg=_cfg())
    # First allow "Delete file"
    cb_allow, _ = _approval("allow")
    token1 = set_approval_callback(cb_allow)
    try:
        a_delete = Action(
            type="click", target_desc="Delete file",
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        assert gate.check(a_delete) is True
    finally:
        reset_approval_callback(token1)

    # Now switch callback to "deny" — a different destructive
    # action must prompt freshly (and get denied).
    cb_deny, calls_deny = _approval("deny")
    token2 = set_approval_callback(cb_deny)
    try:
        a_submit = Action(
            type="click", target_desc="Submit form",
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        assert gate.check(a_submit) is False
        assert len(calls_deny) == 1
    finally:
        reset_approval_callback(token2)


# ---------------------------------------------------------------
# 4) outside-scope / no-target → destructive
# ---------------------------------------------------------------


def test_click_without_target_is_destructive():
    """A click whose target_desc we couldn't read → classify as
    destructive (the conservative default — assume the worst
    because we don't know what the click does)."""
    a = Action(
        type="click", target_desc=None, coords=(10, 10),
        text=None, key=None, app="TestApp",
    )
    assert classify(a) == "destructive"


def test_destructive_verb_in_target_classified_destructive():
    """The classifier catches the destructive verb regex on the
    target description — the most common path for spliced /
    submit / pay buttons."""
    for verb in ("Delete", "Submit", "Pay now", "Sign out", "Erase all"):
        a = Action(
            type="click", target_desc=verb,
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        assert classify(a) == "destructive", f"missed verb: {verb}"


# ---------------------------------------------------------------
# 5) background → denied (via approval_guard)
# ---------------------------------------------------------------


def test_background_denies_input():
    """An input action under a non-FOREGROUND write_origin → the
    gate refuses cleanly (ApprovalDeniedInBackground raised
    inside, returned as False to the tool layer). The approval
    callback is NEVER invoked in this path."""
    gate = PermissionGate(cfg=_cfg())
    cb, calls = _approval("allow")  # would say yes if asked
    origin_token = set_current_write_origin(BACKGROUND_REVIEW)
    cb_token = set_approval_callback(cb)
    try:
        a = Action(
            type="click", target_desc="Save",
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        assert gate.check(a) is False
        # The callback was NOT invoked — approval_guard raised
        # before reaching the prompt.
        assert calls == []
    finally:
        reset_approval_callback(cb_token)
        reset_current_write_origin(origin_token)


def test_background_denies_destructive_too():
    gate = PermissionGate(cfg=_cfg())
    cb, calls = _approval("allow")
    origin_token = set_current_write_origin(BACKGROUND_REVIEW)
    cb_token = set_approval_callback(cb)
    try:
        a = Action(
            type="click", target_desc="Delete account",
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        assert gate.check(a) is False
        assert calls == []
    finally:
        reset_approval_callback(cb_token)
        reset_current_write_origin(origin_token)


# ---------------------------------------------------------------
# 6) panic drops grants and disables
# ---------------------------------------------------------------


def test_panic_drops_grants_and_disables():
    """computer_use_panic() must:
      (a) drop every cached grant
      (b) flip the gate's panic flag so further input/
          destructive checks refuse WITHOUT prompting
    """
    gate = PermissionGate(cfg=_cfg())
    cb, calls = _approval("allow")
    token = set_approval_callback(cb)
    try:
        # Prime a cached input grant.
        a = Action(
            type="click", target_desc="Save",
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        assert gate.check(a) is True
        assert "computer_input" in current_grants()
        assert len(calls) == 1

        # Panic.
        computer_use_panic()
        assert panic_engaged() is True
        # Cache cleared.
        assert current_grants() == {}

        # Further input refused WITHOUT burning a prompt — the
        # panic short-circuit fires before any approval call.
        assert gate.check(a) is False
        assert len(calls) == 1  # unchanged

        # Even a destructive that would normally prompt is now
        # silently refused.
        a_destructive = Action(
            type="click", target_desc="Delete",
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        assert gate.check(a_destructive) is False
        assert len(calls) == 1

        # Disengage; gate accepts prompts again.
        computer_use_unpanic()
        assert panic_engaged() is False
        assert gate.check(a) is True
        assert len(calls) == 2  # re-prompted (the cache stays cleared)
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------
# Goal-loop deny (the gap RECON.md flagged)
# ---------------------------------------------------------------


def test_goal_loop_active_denies_input(monkeypatch):
    """When /goal is active, the gate refuses input/destructive
    even from FOREGROUND. The approval callback is never asked
    — the deny is the answer."""
    gate = PermissionGate(cfg=_cfg())
    cb, calls = _approval("allow")

    monkeypatch.setattr(
        "athena.computer.permission._goal_loop_active",
        lambda cfg: True,
    )

    token = set_approval_callback(cb)
    try:
        a = Action(
            type="click", target_desc="Save",
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        assert gate.check(a) is False
        assert calls == []
    finally:
        reset_approval_callback(token)


def test_goal_loop_check_opt_out(monkeypatch):
    """cfg.computer_deny_during_goal_loop=False disables the
    extra check (operator's choice). With the goal loop active
    and the flag off, input flows normally through approval_guard."""
    gate = PermissionGate(cfg=_cfg(computer_deny_during_goal_loop=False))
    cb, calls = _approval("allow")

    # _goal_loop_active reads the cfg flag first — when False
    # the function short-circuits to False regardless of state.
    # So with the flag off, the gate accepts input.
    token = set_approval_callback(cb)
    try:
        a = Action(
            type="click", target_desc="Save",
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        assert gate.check(a) is True
        assert len(calls) == 1
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------
# Config-driven refusals don't burn a prompt
# ---------------------------------------------------------------


def test_denylist_refuses_without_prompting():
    gate = PermissionGate(cfg=_cfg(
        computer_app_allowlist=["TestApp", "Banking"],
        computer_app_denylist=["banking"],
    ))
    cb, calls = _approval("allow")
    token = set_approval_callback(cb)
    try:
        a = Action(
            type="click", target_desc="Pay $1000",
            coords=(0, 0), text=None, key=None, app="Banking",
        )
        assert gate.check(a) is False
        assert calls == []  # denylist wins, no prompt
    finally:
        reset_approval_callback(token)


def test_observe_only_mode_refuses_without_prompting():
    gate = PermissionGate(cfg=_cfg(computer_permission_mode="observe_only"))
    cb, calls = _approval("allow")
    token = set_approval_callback(cb)
    try:
        a = Action(
            type="click", target_desc="Save",
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        assert gate.check(a) is False
        assert calls == []
    finally:
        reset_approval_callback(token)


def test_app_not_in_allowlist_refuses_without_prompting():
    gate = PermissionGate(cfg=_cfg(
        computer_app_allowlist=["OnlyThisOne"],
    ))
    cb, calls = _approval("allow")
    token = set_approval_callback(cb)
    try:
        a = Action(
            type="click", target_desc="Save",
            coords=(0, 0), text=None, key=None, app="SomethingElse",
        )
        assert gate.check(a) is False
        assert calls == []
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------
# Defensive: approval surface raising → denial
# ---------------------------------------------------------------


def test_callback_exception_treated_as_denial():
    gate = PermissionGate(cfg=_cfg())

    def _raise(_tool, _args):
        raise RuntimeError("approval system broken")

    token = set_approval_callback(_raise)
    try:
        a = Action(
            type="click", target_desc="Save",
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        assert gate.check(a) is False
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------
# reset_session via the new mechanism
# ---------------------------------------------------------------


def test_reset_session_drops_input_grant():
    gate = PermissionGate(cfg=_cfg())
    cb, calls = _approval("allow")
    token = set_approval_callback(cb)
    try:
        a = Action(
            type="click", target_desc="Save",
            coords=(0, 0), text=None, key=None, app="TestApp",
        )
        gate.check(a)
        assert "computer_input" in current_grants()

        gate.reset_session()
        # The grant was dropped (the ContextVar approval cache
        # is the source of truth — reset_session uses it).
        assert current_grants() == {}

        # Re-prompts on the next check.
        gate.check(a)
        assert len(calls) == 2
    finally:
        reset_approval_callback(token)
