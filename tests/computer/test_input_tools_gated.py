"""T6-04R.4 — input tools route through the gate (the load-bearing
no-bypass invariant).

These pin that EVERY input tool (click / type / key / scroll)
goes through the gate before reaching ``backend.perform``. The
gate denies → backend is NEVER touched. Pinned via a spy
backend that records every perform call.

Also pins:
  - input tool refusal is structured (JSON with tier + reason);
    the model can reason about it
  - destructive verbs in target_desc force the destructive path
    even when the user happens to have an "input" grant cached
  - background context refuses every input/destructive without
    ever touching the backend
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.computer import tools as tools_mod
from athena.computer.contract import Action, ActionType, Screenshot
from athena.provenance import (
    BACKGROUND_REVIEW,
    reset_current_write_origin,
    set_current_write_origin,
)
from athena.safety.approval_callback import (
    reset_approval_callback,
    set_approval_callback,
)
from athena.safety.approval_guard import current_grants


# ---------------------------------------------------------------
# Spy backend — every perform call is recorded; nothing reaches
# the OS.
# ---------------------------------------------------------------


class _SpyBackend:
    name = "spy"

    def __init__(self, *, app: str = "TestApp"):
        self._app = app
        self.perform_calls: list[Action] = []

    def is_available(self) -> bool:
        return True

    def supports(self) -> list[ActionType]:
        return ["screenshot", "click", "type", "key", "scroll"]

    def screenshot(self) -> Screenshot:
        return Screenshot(png_bytes=b"frame", width=10, height=10, scale=1.0)

    def active_app(self):
        return self._app

    def accessibility_tree(self):
        return None

    def perform(self, action: Action) -> None:
        self.perform_calls.append(action)


def _cfg(tmp_path: Path, **overrides: Any) -> SimpleNamespace:
    """Stub Config shaped for post-R4 nested ``cfg.computer.*`` reads."""
    legacy_to_nested = {
        "computer_use_enabled": "use_enabled",
        "computer_permission_mode": "permission_mode",
        "computer_app_allowlist": "app_allowlist",
        "computer_app_denylist": "app_denylist",
        "computer_audit_path": "audit_path",
        "computer_screenshots_dir": "screenshots_dir",
        "computer_deny_during_goal_loop": "deny_during_goal_loop",
        "computer_kill_hotkey": "kill_hotkey",
        "computer_max_actions_per_task": "max_actions_per_task",
        "computer_max_actions_per_sec": "max_actions_per_sec",
        "computer_backend": "backend",
        "computer_dry_run": "dry_run",
    }
    computer_defaults = dict(
        use_enabled=True,
        permission_mode="per_action",
        app_allowlist=["TestApp"],
        app_denylist=[],
        kill_hotkey="ctrl+alt+k",
        max_actions_per_task=40,
        max_actions_per_sec=2.0,
        backend="auto",
        dry_run=False,
        audit_path=str(tmp_path / "audit.jsonl"),
        screenshots_dir=str(tmp_path / "shots"),
        deny_during_goal_loop=False,
    )
    top_defaults: dict = {"profile": "default"}
    for k, v in overrides.items():
        if k in legacy_to_nested:
            computer_defaults[legacy_to_nested[k]] = v
        elif k in computer_defaults:
            computer_defaults[k] = v
        else:
            top_defaults[k] = v
    return SimpleNamespace(
        computer=SimpleNamespace(**computer_defaults),
        **top_defaults,
    )


@pytest.fixture
def _spy_setup(monkeypatch, tmp_path: Path):
    backend = _SpyBackend()
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))
    monkeypatch.setattr(tools_mod, "select_backend", lambda cfg: backend)
    # tools.py caches _backend + _audit globally; reset so each
    # test gets a fresh resolution onto THIS spy backend.
    tools_mod._reset_for_tests()
    yield backend
    tools_mod._reset_for_tests()


def _allow():
    return set_approval_callback(lambda _tool, _args: "allow")


def _deny():
    return set_approval_callback(lambda _tool, _args: "deny")


# ---------------------------------------------------------------
# Happy paths — gate approves → backend fires
# ---------------------------------------------------------------


def test_click_goes_through_gate(_spy_setup):
    token = _allow()
    try:
        out = json.loads(tools_mod.computer_click(
            x=10, y=10, target_desc="Tab 2",
        ))
        assert out["performed"] is True
        assert len(_spy_setup.perform_calls) == 1
        assert _spy_setup.perform_calls[0].type == "click"
        # Grant cached under the input key for follow-ups.
        assert "computer_input" in current_grants()
    finally:
        reset_approval_callback(token)


def test_type_goes_through_gate(_spy_setup):
    token = _allow()
    try:
        out = json.loads(tools_mod.computer_type(text="hello"))
        assert out["performed"] is True
        assert len(_spy_setup.perform_calls) == 1
        assert _spy_setup.perform_calls[0].type == "type"
    finally:
        reset_approval_callback(token)


def test_submit_takes_destructive_path(_spy_setup):
    """A click with target_desc='Submit' → destructive tier. The
    gate prompts via approval_guard's destructive resource_id."""
    asks: list[str] = []

    def _cb(tool_name: str, args: dict) -> str:
        asks.append(args.get("tier", "?"))
        return "allow"

    token = set_approval_callback(_cb)
    try:
        out = json.loads(tools_mod.computer_click(
            x=10, y=10, target_desc="Submit form",
        ))
        assert out["performed"] is True
        assert asks == ["destructive"]
    finally:
        reset_approval_callback(token)


# ---------------------------------------------------------------
# THE LOAD-BEARING INVARIANT — no input tool bypasses the gate
# ---------------------------------------------------------------


def test_denied_input_never_touches_backend(_spy_setup):
    """The gate denies → perform_calls stays empty. Refusal is
    structured."""
    token = _deny()
    try:
        out = json.loads(tools_mod.computer_click(
            x=10, y=10, target_desc="Save",
        ))
        assert out["performed"] is False
        assert out["tier"] == "input"
        assert "denied" in out["reason"]
        assert _spy_setup.perform_calls == []
    finally:
        reset_approval_callback(token)


def test_denied_destructive_never_touches_backend(_spy_setup):
    token = _deny()
    try:
        out = json.loads(tools_mod.computer_click(
            x=10, y=10, target_desc="Delete file",
        ))
        assert out["performed"] is False
        assert out["tier"] == "destructive"
        assert _spy_setup.perform_calls == []
    finally:
        reset_approval_callback(token)


def test_background_origin_blocks_every_tool(_spy_setup):
    """Under BACKGROUND_REVIEW (a fork running tools), every
    input + destructive call refuses without consulting the
    backend. The approval callback is NEVER invoked — the
    background-deny fires before the prompt."""
    callback_calls: list = []

    def _cb(tool_name: str, args: dict) -> str:
        callback_calls.append((tool_name, args))
        return "allow"

    origin_token = set_current_write_origin(BACKGROUND_REVIEW)
    cb_token = set_approval_callback(_cb)
    try:
        for fn, kw in [
            (tools_mod.computer_click, dict(x=10, y=10, target_desc="Save")),
            (tools_mod.computer_type, dict(text="hello")),
            (tools_mod.computer_key, dict(key="ctrl+s")),
            (tools_mod.computer_scroll, dict(x=10, y=10, dy=3)),
        ]:
            out = json.loads(fn(**kw))
            assert out["performed"] is False
        assert _spy_setup.perform_calls == []
        assert callback_calls == []
    finally:
        reset_approval_callback(cb_token)
        reset_current_write_origin(origin_token)


def test_audit_log_records_tier_for_every_action(_spy_setup, tmp_path: Path):
    """Every action — allowed and denied — lands in the audit
    log with its tier + the result. T6-04R doesn't change this
    contract; the test pins it across the new code path."""
    token = _allow()
    try:
        tools_mod.computer_click(x=10, y=10, target_desc="Tab 2")
        tools_mod.computer_click(x=20, y=20, target_desc="Delete file")
    finally:
        reset_approval_callback(token)

    audit = tmp_path / "audit.jsonl"
    assert audit.exists()
    rows = [json.loads(l) for l in audit.read_text().splitlines() if l.strip()]
    tiers = [r.get("tier") for r in rows]
    assert "input" in tiers
    assert "destructive" in tiers


# ---------------------------------------------------------------
# Tools refuse when disabled regardless of approval
# ---------------------------------------------------------------


def test_disabled_short_circuits_input_too(monkeypatch, tmp_path: Path):
    """cfg.computer_use_enabled=False → input tool refuses with
    NO backend contact AND NO approval prompt. Verified by
    counting both backend.perform calls and approval callback
    invocations."""
    backend = _SpyBackend()
    monkeypatch.setattr(
        tools_mod, "_load_cfg",
        lambda: _cfg(tmp_path, computer_use_enabled=False),
    )
    monkeypatch.setattr(tools_mod, "select_backend", lambda cfg: backend)

    callback_calls: list = []

    def _record(_t, _a):
        callback_calls.append(1)
        return "allow"

    token = set_approval_callback(_record)
    try:
        out = json.loads(tools_mod.computer_click(
            x=10, y=10, target_desc="Save",
        ))
        assert out["available"] is False
        assert backend.perform_calls == []
        assert callback_calls == []
    finally:
        reset_approval_callback(token)
