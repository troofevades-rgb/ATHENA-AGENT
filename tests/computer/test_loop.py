"""Observe-act loop tests (T6-04.5).

The loop is the single call site of backend.perform — tests
pin that contract along with the kill-switch poll, the caps,
no-op detection, and the dry-run pass-through. The vision
proposer is injected so no real model fires.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.computer import killswitch
from athena.computer.audit import ActionAuditLog
from athena.computer.contract import Action, ActionType, Screenshot
from athena.computer.loop import (
    ActionProposal,
    LoopResult,
    computer_do,
    map_coords,
)
from athena.computer.permission import PermissionGate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SpyBackend:
    """In-test backend recording every interaction. The
    ``screenshots`` iterator yields a new fake screenshot per
    call so no-op detection can be exercised."""

    name = "spy"

    def __init__(
        self,
        *,
        screenshots: list[bytes] | None = None,
        app: str = "TestApp",
    ):
        self._screens = list(screenshots or [b"frame-1"])
        self._idx = 0
        self.perform_calls: list[Action] = []
        self.app = app

    def is_available(self) -> bool:
        return True

    def supports(self) -> list[ActionType]:
        return ["screenshot", "click", "type", "key", "scroll"]

    def screenshot(self) -> Screenshot:
        # Rolls forward through the configured sequence; sticks
        # on the last one so a long loop doesn't run out of
        # frames.
        idx = min(self._idx, len(self._screens) - 1)
        self._idx += 1
        return Screenshot(
            png_bytes=self._screens[idx],
            width=200,
            height=100,
            scale=1.0,
        )

    def active_app(self):
        return self.app

    def accessibility_tree(self):
        return None

    def perform(self, action: Action) -> None:
        self.perform_calls.append(action)


def _cfg(tmp_path: Path, **overrides) -> SimpleNamespace:
    base = dict(
        computer_use_enabled=True,
        computer_permission_mode="per_action",
        computer_app_allowlist=["TestApp"],
        computer_app_denylist=[],
        computer_audit_path=str(tmp_path / "audit.jsonl"),
        computer_max_actions_per_task=10,
        computer_max_actions_per_sec=10000.0,  # fast tests
        computer_kill_hotkey=None,
        profile="default",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _gate(cfg: Any, *, confirm_returns: bool = True) -> PermissionGate:
    return PermissionGate(
        cfg=cfg, confirm=lambda a, t: confirm_returns
    )


@pytest.fixture(autouse=True)
def _killswitch_reset():
    killswitch.reset_for_tests()
    yield
    killswitch.reset_for_tests()


# ---------------------------------------------------------------------------
# Coordinate mapping (pure function)
# ---------------------------------------------------------------------------


def test_map_coords_passes_through_in_bounds():
    shot = Screenshot(png_bytes=b"", width=200, height=100)
    assert map_coords((50, 25), screenshot=shot) == (50, 25)


def test_map_coords_clamps_negative():
    shot = Screenshot(png_bytes=b"", width=200, height=100)
    assert map_coords((-5, -10), screenshot=shot) == (0, 0)


def test_map_coords_clamps_over_bounds():
    """Out-of-bounds proposals are clamped, not silently
    accepted — clicking off-screen is a safety issue."""
    shot = Screenshot(png_bytes=b"", width=200, height=100)
    assert map_coords((5000, 5000), screenshot=shot) == (199, 99)


def test_map_coords_none_returns_none():
    shot = Screenshot(png_bytes=b"", width=200, height=100)
    assert map_coords(None, screenshot=shot) is None


def test_coordinate_mapping_scales(tmp_path: Path):
    """A screenshot reports its scale; map_coords currently
    treats screenshot pixels as the same coordinate system as
    backend pixels (no transformation) — but it's the single
    pure entrypoint where any future scaling lives. This test
    pins the current contract."""
    shot = Screenshot(png_bytes=b"", width=200, height=100, scale=2.0)
    assert map_coords((50, 25), screenshot=shot) == (50, 25)
    # Out-of-bounds still clamps to screenshot bounds (not
    # logical/scaled bounds).
    assert map_coords((300, 25), screenshot=shot) == (199, 25)


# ---------------------------------------------------------------------------
# Done signal stops
# ---------------------------------------------------------------------------


def test_loop_done_signal_stops(tmp_path: Path):
    """First proposal returns done=True → loop exits with
    status=done, ZERO perform calls."""
    backend = _SpyBackend()
    cfg = _cfg(tmp_path)
    gate = _gate(cfg)
    audit = ActionAuditLog(tmp_path / "audit.jsonl")

    propose_calls = {"n": 0}

    def _propose(task, shot, history):
        propose_calls["n"] += 1
        return ActionProposal(done=True, message="finished")

    result = computer_do(
        task="x",
        backend=backend,
        gate=gate,
        propose=_propose,
        audit=audit,
        cfg=cfg,
    )
    assert result.status == "done"
    assert result.actions_taken == 0
    assert result.last_message == "finished"
    assert backend.perform_calls == []
    assert propose_calls["n"] == 1


# ---------------------------------------------------------------------------
# Kill switch halts
# ---------------------------------------------------------------------------


def test_loop_halts_on_killswitch(tmp_path: Path):
    """Mid-loop kill-switch engagement → status=halted with the
    reason, NO further perform calls. The loop polls the
    switch at the TOP of every iteration; engaging during the
    propose call is honoured on the NEXT iteration."""
    backend = _SpyBackend(screenshots=[f"f-{i}".encode() for i in range(20)])
    cfg = _cfg(tmp_path, computer_max_actions_per_task=10)
    gate = _gate(cfg)
    audit = ActionAuditLog(tmp_path / "audit.jsonl")
    propose_calls = {"n": 0}

    def _propose(task, shot, history):
        propose_calls["n"] += 1
        if propose_calls["n"] == 2:
            # Engage mid-loop (mirrors a Ctrl+C / hotkey firing
            # from a different thread mid-propose).
            killswitch.engage(reason="mid-loop test halt")
        return ActionProposal(
            done=False,
            action=Action(
                type="click", coords=(10, 10), target_desc="OK", app="TestApp"
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
    assert result.halt_reason == "mid-loop test halt"
    # First iteration performed a click; second iteration's
    # propose engaged the switch; third iteration's top-of-loop
    # check halted before perform fired again.
    assert len(backend.perform_calls) == 2


# ---------------------------------------------------------------------------
# Max-actions cap
# ---------------------------------------------------------------------------


def test_loop_respects_max_actions(tmp_path: Path):
    """Model never says done; loop hits computer_max_actions_per_task
    and stops with status=max_actions."""
    backend = _SpyBackend(
        # Each proposed click changes the screen so no-op
        # detection doesn't kick in first.
        screenshots=[f"frame-{i}".encode() for i in range(20)]
    )
    cfg = _cfg(tmp_path, computer_max_actions_per_task=3)
    gate = _gate(cfg)
    audit = ActionAuditLog(tmp_path / "audit.jsonl")

    def _propose(task, shot, history):
        return ActionProposal(
            done=False,
            action=Action(
                type="click", coords=(10, 10), target_desc="Tab", app="TestApp"
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
    assert result.status == "max_actions"
    assert result.actions_taken == 3
    assert len(backend.perform_calls) == 3


# ---------------------------------------------------------------------------
# THE INVARIANT: denied action is NEVER performed
# ---------------------------------------------------------------------------


def test_loop_denied_action_not_performed(tmp_path: Path):
    """A gate denial → backend.perform NEVER called for that
    action. The single safety invariant of the whole feature."""
    backend = _SpyBackend(screenshots=[f"f-{i}".encode() for i in range(20)])
    cfg = _cfg(
        tmp_path,
        computer_app_allowlist=["TestApp"],
        computer_max_actions_per_task=3,
    )
    gate = _gate(cfg, confirm_returns=False)  # deny everything

    audit = ActionAuditLog(tmp_path / "audit.jsonl")

    def _propose(task, shot, history):
        return ActionProposal(
            done=False,
            action=Action(
                type="click",
                coords=(10, 10),
                target_desc="Delete",  # destructive
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
    # The loop kept running (proposals stayed denied; loop hit
    # max actions of denials, which counts in propose calls,
    # not in actions_taken).
    assert result.actions_taken == 0  # nothing performed
    assert backend.perform_calls == []  # the invariant
    # Audit log captured every denial.
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "denied" in text


def test_loop_observe_only_blocks_input_entirely(tmp_path: Path):
    """The observe_only mode at the gate level → no perform
    calls regardless of what the model proposes."""
    backend = _SpyBackend(screenshots=[f"f-{i}".encode() for i in range(20)])
    cfg = _cfg(
        tmp_path,
        computer_permission_mode="observe_only",
        computer_app_allowlist=["TestApp"],
        computer_max_actions_per_task=2,
    )
    # observe_only refuses without prompting; gate's confirm is
    # irrelevant.
    gate = PermissionGate(cfg=cfg, confirm=lambda a, t: True)
    audit = ActionAuditLog(tmp_path / "audit.jsonl")

    def _propose(task, shot, history):
        return ActionProposal(
            done=False,
            action=Action(
                type="click", coords=(5, 5), target_desc="OK", app="TestApp"
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
    assert backend.perform_calls == []


# ---------------------------------------------------------------------------
# No-op detection
# ---------------------------------------------------------------------------


def test_noop_detection_stops(tmp_path: Path):
    """When the screen doesn't change after the configured
    threshold (4) of denied/idle iterations, the loop stops
    with status=stuck."""
    # Single frame repeated — no change ever.
    backend = _SpyBackend(screenshots=[b"same-frame"])
    cfg = _cfg(
        tmp_path,
        computer_app_allowlist=["TestApp"],
        computer_max_actions_per_task=20,
    )
    # Deny every action so the screen never changes from the
    # loop's input — combined with the static screenshot the
    # no-op count climbs.
    gate = _gate(cfg, confirm_returns=False)
    audit = ActionAuditLog(tmp_path / "audit.jsonl")

    def _propose(task, shot, history):
        return ActionProposal(
            done=False,
            action=Action(
                type="click",
                coords=(5, 5),
                target_desc="Delete",  # destructive, gets denied
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
    assert result.status == "stuck"
    assert backend.perform_calls == []


# ---------------------------------------------------------------------------
# Vision proposer failure
# ---------------------------------------------------------------------------


def test_loop_handles_propose_exception(tmp_path: Path):
    backend = _SpyBackend()
    cfg = _cfg(tmp_path)
    gate = _gate(cfg)
    audit = ActionAuditLog(tmp_path / "audit.jsonl")

    def _propose(task, shot, history):
        raise RuntimeError("vision failed")

    result = computer_do(
        task="x",
        backend=backend,
        gate=gate,
        propose=_propose,
        audit=audit,
        cfg=cfg,
    )
    assert result.status == "error"
    assert "vision failed" in result.halt_reason


# ---------------------------------------------------------------------------
# Backend.perform failure
# ---------------------------------------------------------------------------


def test_loop_handles_perform_exception(tmp_path: Path):
    """If perform raises mid-task, the loop exits with
    status=error and the audit log captures the failure."""

    class _BadBackend(_SpyBackend):
        def perform(self, action: Action) -> None:
            raise RuntimeError("perform exploded")

    backend = _BadBackend(screenshots=[f"f-{i}".encode() for i in range(10)])
    cfg = _cfg(tmp_path)
    gate = _gate(cfg)
    audit = ActionAuditLog(tmp_path / "audit.jsonl")

    def _propose(task, shot, history):
        return ActionProposal(
            done=False,
            action=Action(
                type="click", coords=(10, 10), target_desc="OK", app="TestApp"
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
    assert result.status == "error"
    assert "perform exploded" in result.halt_reason


# ---------------------------------------------------------------------------
# Dry-run — every gate-allowed action audit-logged BUT never performed
# ---------------------------------------------------------------------------


def test_dry_run_logs_but_does_not_perform(tmp_path: Path):
    backend = _SpyBackend(screenshots=[f"f-{i}".encode() for i in range(10)])
    cfg = _cfg(tmp_path, computer_max_actions_per_task=3)
    gate = _gate(cfg)
    audit = ActionAuditLog(tmp_path / "audit.jsonl")

    def _propose(task, shot, history):
        return ActionProposal(
            done=False,
            action=Action(
                type="click", coords=(5, 5), target_desc="Tab", app="TestApp"
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
    # Loop ran to the max-actions cap, but perform was never
    # called.
    assert backend.perform_calls == []
    assert result.actions_taken == 3  # counted; dry-run still counts
    # Audit log has "dry-run" result entries.
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "dry-run" in text


# ---------------------------------------------------------------------------
# Vision returned no action
# ---------------------------------------------------------------------------


def test_loop_no_action_proposed_stops(tmp_path: Path):
    backend = _SpyBackend()
    cfg = _cfg(tmp_path)
    gate = _gate(cfg)
    audit = ActionAuditLog(tmp_path / "audit.jsonl")

    def _propose(task, shot, history):
        return ActionProposal(done=False, action=None)

    result = computer_do(
        task="x",
        backend=backend,
        gate=gate,
        propose=_propose,
        audit=audit,
        cfg=cfg,
    )
    assert result.status == "stuck"
    assert "no action" in result.halt_reason
