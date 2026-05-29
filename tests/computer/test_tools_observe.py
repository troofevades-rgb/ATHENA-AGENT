"""Observe-tool tests (T6-04.4).

Exercises computer_screenshot + computer_observe against a
stubbed backend so no real screen capture fires. The
load-bearing properties:

  * Disabled by default — cfg.computer_use_enabled=False →
    structured "not enabled" payload, NO backend contact
  * Observe captures land in the audit log with the screenshot
    hash
  * Unavailable backend (no platform support) → structured
    "not available", no crash
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.computer import tools as tools_mod
from athena.computer.contract import Action, ActionType, Screenshot


class _StubBackend:
    """In-test backend that returns canned screenshots + app
    names. NEVER touches the OS."""

    name = "stub"

    def __init__(
        self,
        *,
        available: bool = True,
        screenshot_payload: bytes = b"stub-pixels",
        app: str | None = "TestApp",
        raise_on_screenshot: Exception | None = None,
    ):
        self._available = available
        self._payload = screenshot_payload
        self._app = app
        self._raise = raise_on_screenshot

    def is_available(self) -> bool:
        return self._available

    def supports(self) -> list[ActionType]:
        return ["screenshot"]

    def screenshot(self) -> Screenshot:
        if self._raise is not None:
            raise self._raise
        return Screenshot(
            png_bytes=self._payload, width=200, height=100, scale=1.0
        )

    def active_app(self):
        return self._app

    def accessibility_tree(self):
        return None

    def perform(self, action: Action) -> None:
        raise NotImplementedError


def _cfg(tmp_path: Path, **overrides) -> SimpleNamespace:
    """Stub Config shaped for post-R4 nested ``cfg.computer.*`` reads.

    Test overrides can pass either the legacy ``computer_X`` flat
    names (translated to nested) or the new ``X`` names directly."""
    legacy_to_nested = {
        "computer_use_enabled": "use_enabled",
        "computer_permission_mode": "permission_mode",
        "computer_app_allowlist": "app_allowlist",
        "computer_app_denylist": "app_denylist",
        "computer_kill_hotkey": "kill_hotkey",
        "computer_max_actions_per_task": "max_actions_per_task",
        "computer_max_actions_per_sec": "max_actions_per_sec",
        "computer_backend": "backend",
        "computer_dry_run": "dry_run",
        "computer_audit_path": "audit_path",
        "computer_screenshots_dir": "screenshots_dir",
        "computer_deny_during_goal_loop": "deny_during_goal_loop",
    }
    computer_defaults = dict(
        use_enabled=True,
        permission_mode="observe_only",
        app_allowlist=[],
        app_denylist=[],
        kill_hotkey="ctrl+alt+k",
        max_actions_per_task=40,
        max_actions_per_sec=2.0,
        backend="auto",
        dry_run=False,
        audit_path=str(tmp_path / "audit.jsonl"),
        screenshots_dir=str(tmp_path / "screenshots"),
        deny_during_goal_loop=True,
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


@pytest.fixture(autouse=True)
def _clean_module_cache():
    tools_mod._reset_for_tests()
    yield
    tools_mod._reset_for_tests()


# ---------------------------------------------------------------------------
# Disabled-by-default contract
# ---------------------------------------------------------------------------


def test_screenshot_refuses_when_disabled(monkeypatch, tmp_path: Path):
    """cfg.computer_use_enabled=False → tool returns the
    structured "not enabled" payload WITHOUT contacting the
    backend. The opt-in invariant."""
    backend_calls = {"n": 0}

    class _MustNotRun:
        name = "must-not-run"

        def is_available(self):
            backend_calls["n"] += 1
            return True

    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path, computer_use_enabled=False))
    monkeypatch.setattr(tools_mod, "select_backend", lambda cfg: _MustNotRun())

    out = json.loads(tools_mod.computer_screenshot())
    assert out["available"] is False
    # Post-R4 the message references the new nested path.
    assert "use_enabled" in out["reason"]
    assert backend_calls["n"] == 0


def test_observe_refuses_when_disabled(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path, computer_use_enabled=False))
    out = json.loads(tools_mod.computer_observe(question="anything"))
    assert out["available"] is False


# ---------------------------------------------------------------------------
# Backend unavailable
# ---------------------------------------------------------------------------


def test_screenshot_when_backend_unavailable(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))
    monkeypatch.setattr(
        tools_mod, "select_backend", lambda cfg: _StubBackend(available=False)
    )
    out = json.loads(tools_mod.computer_screenshot())
    assert out["available"] is False
    assert "not available" in out["reason"]


def test_screenshot_backend_error_returns_structured(monkeypatch, tmp_path: Path):
    """A backend exception → structured payload, never
    propagates."""
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))
    monkeypatch.setattr(
        tools_mod,
        "select_backend",
        lambda cfg: _StubBackend(raise_on_screenshot=RuntimeError("BitBlt died")),
    )
    out = json.loads(tools_mod.computer_screenshot())
    assert out["available"] is False
    assert "BitBlt died" in out["reason"]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_screenshot_returns_image_and_logs(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))
    monkeypatch.setattr(
        tools_mod, "select_backend", lambda cfg: _StubBackend()
    )

    out = json.loads(tools_mod.computer_screenshot())
    assert out["available"] is True
    assert out["backend"] == "stub"
    assert out["width"] == 200
    assert out["height"] == 100
    # T6-04.4 follow-up: payload is a PATH on disk, not
    # inline base64 (a 4K screen would blow the local model's
    # context window otherwise).
    assert "path" in out
    assert "image_b64" not in out
    persisted = Path(out["path"])
    assert persisted.exists()
    assert persisted.read_bytes() == b"stub-pixels"
    assert out["sha256"]
    assert out["bytes"] == len(b"stub-pixels")

    # Audit log line written.
    audit_file = tmp_path / "audit.jsonl"
    assert audit_file.exists()
    raw = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(raw) == 1
    row = json.loads(raw[0])
    assert row["type"] == "screenshot"
    assert row["tier"] == "observe"
    assert row["executed"] is True
    assert row["result"] == "ok"


def test_screenshot_payload_NEVER_in_audit_log(monkeypatch, tmp_path: Path):
    """A second invariant pin: the screenshot bytes don't leak
    into the audit JSON even when they contain sensitive
    content."""
    secret = b"USERS-CONFIDENTIAL-SCREEN-CONTENT-DO-NOT-LEAK"
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))
    monkeypatch.setattr(
        tools_mod,
        "select_backend",
        lambda cfg: _StubBackend(screenshot_payload=secret),
    )
    tools_mod.computer_screenshot()
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "USERS-CONFIDENTIAL-SCREEN-CONTENT" not in text


# ---------------------------------------------------------------------------
# computer_observe + vision routing
# ---------------------------------------------------------------------------


def test_observe_empty_question_rejected(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))
    monkeypatch.setattr(
        tools_mod, "select_backend", lambda cfg: _StubBackend()
    )
    out = json.loads(tools_mod.computer_observe(question=""))
    assert out["available"] is False
    assert "question" in out["reason"]


def test_observe_no_vision_backend(monkeypatch, tmp_path: Path):
    """When no vision provider declares the capability, observe
    captures the screen and surfaces "no vision backend" — the
    user can install a vision-capable provider or fall through
    to a base64 screenshot the agent passes elsewhere."""
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))
    monkeypatch.setattr(
        tools_mod, "select_backend", lambda cfg: _StubBackend()
    )

    # Empty vision capability set. Two patch sites needed: the
    # source-of-truth registry AND the imported alias inside
    # media/registry.py — monkeypatch.setattr on the module
    # attribute doesn't propagate to a name that was already
    # bound via `from .. import _REGISTRY`.
    monkeypatch.setattr("athena.providers._REGISTRY", {})
    monkeypatch.setattr("athena.media.registry._REGISTRY", {})

    out = json.loads(tools_mod.computer_observe(question="what's on screen?"))
    assert out["available"] is True
    assert out["vision_backend"] is None
    assert "no vision backend" in out["reason"]


def test_observe_resolves_vision_backend(monkeypatch, tmp_path: Path):
    """A provider declaring vision in its manifest → tool
    routes the observe through it. Tool surfaces the backend
    name + the image payload for the agent runtime to dispatch."""
    from athena.providers.base import Capabilities, Provider

    class _VisionStub(Provider):
        pass

    _VisionStub.name = "stub_vision"
    _VisionStub.static_capabilities = classmethod(
        lambda cls, model=None: Capabilities(vision=True, is_local=True)
    )  # type: ignore[method-assign]

    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))
    monkeypatch.setattr(
        tools_mod, "select_backend", lambda cfg: _StubBackend()
    )
    monkeypatch.setattr("athena.providers._REGISTRY", {"stub_vision": _VisionStub})
    monkeypatch.setattr("athena.media.registry._REGISTRY", {"stub_vision": _VisionStub})

    out = json.loads(tools_mod.computer_observe(question="what app is this?"))
    assert out["available"] is True
    assert out["vision_backend"] == "stub_vision"
    assert out["question"] == "what app is this?"
    assert out["width"] == 200
    # Path-on-disk shape, not inline base64.
    assert "image_b64" not in out
    assert "path" in out
    assert Path(out["path"]).exists()
    assert out["screenshot_sha256"]
