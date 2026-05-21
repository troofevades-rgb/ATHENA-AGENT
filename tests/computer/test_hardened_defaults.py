"""End-to-end hardened-default verification (T6-04.6).

Verifies the safety stance documented in the design doc:

  * Fresh config → computer_use_enabled=False → EVERY computer
    tool refuses without contacting the backend.
  * Enabled + observe_only → observe works; every input refuses.
  * per_action → each input prompts; destructive prompts every
    time even mid-session.
  * Denylisted app → never controlled, no prompt.
  * Ctrl+C / kill hotkey → instant halt mid-task.

These tests exercise the public surfaces (tools + loop +
gate) end-to-end with stubbed OS contact so they run in CI
without a desktop.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.computer import killswitch
from athena.computer import tools as tools_mod
from athena.computer.audit import ActionAuditLog
from athena.computer.contract import Action, ActionType, Screenshot
from athena.computer.loop import ActionProposal, computer_do
from athena.computer.permission import PermissionGate
from athena.config import Config


# ---------------------------------------------------------------------------
# Backend stub
# ---------------------------------------------------------------------------


class _StubBackend:
    name = "stub"

    def __init__(self, app: str = "TestApp"):
        self.perform_calls: list[Action] = []
        self._app = app

    def is_available(self) -> bool:
        return True

    def supports(self) -> list[ActionType]:
        return ["screenshot", "click", "type", "key", "scroll"]

    def screenshot(self) -> Screenshot:
        return Screenshot(png_bytes=b"frame", width=100, height=80, scale=1.0)

    def active_app(self):
        return self._app

    def accessibility_tree(self):
        return None

    def perform(self, action: Action) -> None:
        self.perform_calls.append(action)


@pytest.fixture(autouse=True)
def _reset():
    tools_mod._reset_for_tests()
    killswitch.reset_for_tests()
    yield
    tools_mod._reset_for_tests()
    killswitch.reset_for_tests()


# ---------------------------------------------------------------------------
# 1. Fresh config — every tool refuses, no backend contact
# ---------------------------------------------------------------------------


def test_fresh_config_disables_every_tool(monkeypatch, tmp_path: Path):
    """The default Config() has computer_use_enabled=False. The
    invariant test: every computer_* tool refuses with a
    structured payload AND never even calls is_available on
    the backend."""
    cfg = Config()
    # Plant a backend that records EVERY call.
    contacted = {"n": 0}

    class _Tripwire:
        name = "tripwire"

        def is_available(self):
            contacted["n"] += 1
            return True

        def supports(self):
            contacted["n"] += 1
            return []

        def screenshot(self):
            contacted["n"] += 1
            raise AssertionError("backend must not be contacted when disabled")

        def active_app(self):
            return None

        def accessibility_tree(self):
            return None

        def perform(self, a):
            raise AssertionError("perform must not run when disabled")

    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: cfg)
    monkeypatch.setattr(tools_mod, "select_backend", lambda c: _Tripwire())

    out1 = json.loads(tools_mod.computer_screenshot())
    assert out1["available"] is False
    assert "computer_use_enabled" in out1["reason"]

    out2 = json.loads(tools_mod.computer_observe(question="anything"))
    assert out2["available"] is False

    out3 = json.loads(tools_mod.computer_click(x=10, y=10, target_desc="OK"))
    assert out3["available"] is False

    out4 = json.loads(tools_mod.computer_type(text="hello"))
    assert out4["available"] is False

    out5 = json.loads(tools_mod.computer_key(key="Return"))
    assert out5["available"] is False

    assert contacted["n"] == 0


def test_default_mode_is_observe_only():
    cfg = Config()
    assert cfg.computer_permission_mode == "observe_only"


def test_default_allowlist_is_empty():
    """The safest possible default: no app is approved for
    control. Even with the user enabling computer_use, no
    input runs until they explicitly allowlist an app."""
    cfg = Config()
    assert cfg.computer_app_allowlist == []


def test_default_denylist_includes_credentials_apps():
    """Sensible out-of-box guards — password managers and
    finance apps are denylisted by default."""
    cfg = Config()
    deny = cfg.computer_app_denylist
    for needle in ("password", "bitwarden", "banking", "wallet"):
        assert any(needle in d.lower() for d in deny), (
            f"expected default denylist to include {needle!r}: {deny}"
        )


# ---------------------------------------------------------------------------
# 2. Enabled + observe_only → observe works, every input refuses
# ---------------------------------------------------------------------------


def test_observe_only_allows_screenshot(monkeypatch, tmp_path: Path):
    cfg = SimpleNamespace(
        computer_use_enabled=True,
        computer_permission_mode="observe_only",
        computer_app_allowlist=[],
        computer_app_denylist=[],
        computer_audit_path=str(tmp_path / "audit.jsonl"),
        profile="default",
    )
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: cfg)
    monkeypatch.setattr(tools_mod, "select_backend", lambda c: _StubBackend())
    out = json.loads(tools_mod.computer_screenshot())
    assert out["available"] is True
    assert out["width"] == 100


def test_observe_only_blocks_every_input(monkeypatch, tmp_path: Path):
    cfg = SimpleNamespace(
        computer_use_enabled=True,
        computer_permission_mode="observe_only",
        computer_app_allowlist=["TestApp"],  # even when allowlisted
        computer_app_denylist=[],
        computer_audit_path=str(tmp_path / "audit.jsonl"),
        profile="default",
    )
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: cfg)
    backend = _StubBackend()
    monkeypatch.setattr(tools_mod, "select_backend", lambda c: backend)

    out = json.loads(tools_mod.computer_click(x=10, y=10, target_desc="OK"))
    assert out["performed"] is False
    assert "denied" in out["reason"]
    assert backend.perform_calls == []


# ---------------------------------------------------------------------------
# 3. Denylisted app — no control, no prompt
# ---------------------------------------------------------------------------


def test_denylisted_app_refused_no_prompt(monkeypatch, tmp_path: Path):
    """Even in per_action mode with the user actively approving
    everything, a denylisted app's actions are refused without
    invoking the confirm callback."""
    confirmed: list = []
    cfg = SimpleNamespace(
        computer_use_enabled=True,
        computer_permission_mode="per_action",
        computer_app_allowlist=["1Password 7"],
        computer_app_denylist=["1password"],
        computer_audit_path=str(tmp_path / "audit.jsonl"),
        profile="default",
    )

    # Build the gate manually so we can plant the confirm spy.
    from athena.safety.approval_callback import set_approval_callback
    set_approval_callback(
        lambda _tool, args: (confirmed.append(args.get("tier")) or "allow")
    )
    cfg.computer_deny_during_goal_loop = False
    gate = PermissionGate(cfg=cfg)
    allowed = gate.check(
        Action(type="click", target_desc="OK", app="1Password 7")
    )
    assert allowed is False
    assert confirmed == []  # no prompt — denylist short-circuits


# ---------------------------------------------------------------------------
# 4. per_action prompts each input; destructive every time
# ---------------------------------------------------------------------------


def test_per_action_destructive_always_prompts():
    """Even after granting one destructive, the next destructive
    in the same session prompts again. (Per_action means
    per-action; the test pins it doesn't accidentally batch.)"""
    prompts: list = []
    cfg = SimpleNamespace(
        computer_permission_mode="per_action",
        computer_app_allowlist=["editor"],
        computer_app_denylist=[],
    )
    from athena.safety.approval_callback import set_approval_callback
    set_approval_callback(
        lambda _tool, args: (
            prompts.append((args.get("target_desc"), args.get("tier"))) or "allow"
        )
    )
    cfg.computer_deny_during_goal_loop = False
    gate = PermissionGate(cfg=cfg)
    gate.check(Action(type="click", target_desc="Delete row", app="editor"))
    gate.check(Action(type="click", target_desc="Delete column", app="editor"))
    gate.check(Action(type="click", target_desc="Discard changes", app="editor"))
    assert len(prompts) == 3
    assert all(t == "destructive" for _, t in prompts)


# ---------------------------------------------------------------------------
# 5. Kill switch halts the loop
# ---------------------------------------------------------------------------


def test_kill_switch_halts_end_to_end(tmp_path: Path):
    """Engage mid-loop (from inside propose, mirroring how
    Ctrl+C / hotkey fire from a different thread) → loop exits
    halted, NO subsequent perform calls."""
    backend = _StubBackend()
    cfg = SimpleNamespace(
        computer_use_enabled=True,
        computer_permission_mode="per_action",
        computer_app_allowlist=["TestApp"],
        computer_app_denylist=[],
        computer_audit_path=str(tmp_path / "audit.jsonl"),
        computer_max_actions_per_task=10,
        computer_max_actions_per_sec=10000.0,
        computer_kill_hotkey=None,
        profile="default",
    )
    from athena.safety.approval_callback import set_approval_callback
    set_approval_callback(lambda _tool, _args: "allow")
    cfg.computer_deny_during_goal_loop = False
    gate = PermissionGate(cfg=cfg)
    audit = ActionAuditLog(tmp_path / "audit.jsonl")

    propose_calls = {"n": 0}

    def _propose(task, shot, history):
        propose_calls["n"] += 1
        if propose_calls["n"] == 2:
            killswitch.engage(reason="user pressed Ctrl+C")
        return ActionProposal(
            done=False,
            action=Action(
                type="click",
                coords=(5, 5),
                target_desc="Tab 2",
                app="TestApp",
            ),
        )

    result = computer_do(
        task="x",
        backend=backend,
        gate=gate,
        propose=_propose,
        audit=audit,
        cfg=cfg,
    )
    assert result.status == "halted"
    assert "Ctrl+C" in result.halt_reason
    # Iteration 1: perform fires.
    # Iteration 2: top-of-loop check passes (switch not yet
    #              engaged); propose() engages the switch
    #              mid-iteration; perform STILL fires for this
    #              iteration's action.
    # Iteration 3: top-of-loop check sees engagement; halts
    #              before perform.
    # So two performs land. (To halt before the first perform
    # of iteration 2, the engage would need to happen at the
    # iteration's top — that's what Ctrl+C achieves via SIGINT
    # interrupting whatever was running.)
    assert len(backend.perform_calls) == 2


# ---------------------------------------------------------------------------
# 6. Dry-run end-to-end
# ---------------------------------------------------------------------------


def test_dry_run_end_to_end_never_performs(tmp_path: Path):
    """The full safety story: even with a permissive mode +
    confirm + allowlist, dry_run=True means backend.perform
    is never called."""
    backend = _StubBackend()
    cfg = SimpleNamespace(
        computer_use_enabled=True,
        computer_permission_mode="per_action",
        computer_app_allowlist=["TestApp"],
        computer_app_denylist=[],
        computer_audit_path=str(tmp_path / "audit.jsonl"),
        computer_max_actions_per_task=3,
        computer_max_actions_per_sec=10000.0,
        computer_kill_hotkey=None,
        profile="default",
    )
    from athena.safety.approval_callback import set_approval_callback
    set_approval_callback(lambda _tool, _args: "allow")
    cfg.computer_deny_during_goal_loop = False
    gate = PermissionGate(cfg=cfg)
    audit = ActionAuditLog(tmp_path / "audit.jsonl")

    seq = [f"frame-{i}".encode() for i in range(20)]

    class _ChangingBackend(_StubBackend):
        def __init__(self):
            super().__init__()
            self._i = 0

        def screenshot(self):
            payload = seq[min(self._i, len(seq) - 1)]
            self._i += 1
            return Screenshot(png_bytes=payload, width=100, height=80, scale=1.0)

    backend = _ChangingBackend()

    def _propose(task, shot, history):
        return ActionProposal(
            done=False,
            action=Action(
                type="click",
                coords=(5, 5),
                target_desc="Tab",
                app="TestApp",
            ),
        )

    result = computer_do(
        task="x",
        backend=backend,
        gate=gate,
        propose=_propose,
        audit=audit,
        cfg=cfg,
        dry_run=True,
    )
    assert backend.perform_calls == []
    # The task's plan ran — actions_taken still counts so the
    # operator sees "3 actions would have been performed".
    assert result.actions_taken == 3


# ---------------------------------------------------------------------------
# 7. The single-action tool's no-UI default refuses
# ---------------------------------------------------------------------------


def test_single_action_tools_refuse_without_confirm_ui(monkeypatch, tmp_path: Path):
    """The bare computer_click / computer_type / etc tools
    invoke a default-deny confirm callback because there's no
    REPL/ACP UI plumbed in. The user must wire a real confirm
    via the agent runtime (or the test harness)."""
    cfg = SimpleNamespace(
        computer_use_enabled=True,
        computer_permission_mode="per_action",
        computer_app_allowlist=["TestApp"],
        computer_app_denylist=[],
        computer_audit_path=str(tmp_path / "audit.jsonl"),
        profile="default",
    )
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: cfg)
    backend = _StubBackend()
    monkeypatch.setattr(tools_mod, "select_backend", lambda c: backend)

    out = json.loads(
        tools_mod.computer_click(x=10, y=10, target_desc="Tab 2")
    )
    assert out["performed"] is False
    assert "denied" in out["reason"]
    assert backend.perform_calls == []
