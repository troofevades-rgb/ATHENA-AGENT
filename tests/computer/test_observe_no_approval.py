"""T6-04R.2 — observe-tier needs NO approval.

The retargeted gate routes input/destructive through
approval_guard. Observe tier MUST stay free of any approval
surface so:

  - it works under AUTO_DENY callbacks (fork context)
  - it works when get_current_write_origin() is BACKGROUND_REVIEW
    / CURATOR / MIGRATION / SYSTEM
  - it never calls request_approval (sync or async sibling)
  - it never burns a cached grant

These properties have to keep working through T6-04R.3's gate
refactor.
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
    CURATOR,
    FOREGROUND,
    reset_current_write_origin,
    set_current_write_origin,
)
from athena.safety.approval_callback import (
    AUTO_DENY,
    reset_approval_callback,
    set_approval_callback,
)
from athena.safety.approval_guard import current_grants


# ----- stub backend -----


class _StubBackend:
    name = "stub"

    def __init__(self, *, payload: bytes = b"px", app: str | None = "App"):
        self._payload = payload
        self._app = app

    def is_available(self) -> bool:
        return True

    def supports(self) -> list[ActionType]:
        return ["screenshot"]

    def screenshot(self) -> Screenshot:
        return Screenshot(png_bytes=self._payload, width=10, height=10, scale=1.0)

    def active_app(self):
        return self._app

    def accessibility_tree(self):
        return None

    def perform(self, action: Action) -> None:
        raise NotImplementedError


def _cfg(tmp_path: Path, **overrides: Any) -> SimpleNamespace:
    base = dict(
        computer_use_enabled=True,
        computer_audit_path=str(tmp_path / "audit.jsonl"),
        computer_screenshots_dir=str(tmp_path / "shots"),
        profile="default",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _stub_backend(monkeypatch, tmp_path):
    """Plug the stub backend in for the duration of every test
    so the OS is never touched."""
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))
    monkeypatch.setattr(
        tools_mod, "select_backend", lambda cfg: _StubBackend()
    )
    yield


def test_screenshot_succeeds_under_auto_deny():
    """A fork installs AUTO_DENY as the approval callback. The
    observe path must NOT touch it — screenshot returns
    available=True regardless."""
    token = set_approval_callback(AUTO_DENY)
    try:
        out = json.loads(tools_mod.computer_screenshot())
        assert out["available"] is True
        # No grant was added either.
        assert current_grants() == {}
    finally:
        reset_approval_callback(token)


def test_screenshot_succeeds_in_background_origin():
    """request_approval would raise ApprovalDeniedInBackground
    here. Observe must not call into it."""
    token = set_current_write_origin(BACKGROUND_REVIEW)
    try:
        out = json.loads(tools_mod.computer_screenshot())
        assert out["available"] is True
    finally:
        reset_current_write_origin(token)


def test_observe_succeeds_in_curator_origin(monkeypatch):
    """curator forks have the same constraints as
    background_review. observe still works."""
    # Stub the vision-broker resolution so the observe path
    # doesn't need a real provider class. The vision dispatch
    # is intentionally optional — we're testing the gate, not
    # the vision routing here.
    import athena.media.registry as media_reg
    monkeypatch.setattr(media_reg, "_REGISTRY", {})

    token = set_current_write_origin(CURATOR)
    try:
        out = json.loads(tools_mod.computer_observe(question="what is this?"))
        # available=True regardless of vision provider; if vision is
        # absent the tool surfaces a clear "no vision backend" reason
        # but the SCREENSHOT step succeeded.
        assert out["available"] is True
    finally:
        reset_current_write_origin(token)


def test_observe_does_not_cache_any_grant():
    """Observe must NEVER write to _approval_grants — that
    cache is reserved for input-tier reuse. A grant cached by
    observe would confuse the input gate."""
    assert current_grants() == {}
    tools_mod.computer_screenshot()
    assert current_grants() == {}
    tools_mod.computer_observe(question="anything")
    assert current_grants() == {}


def test_observe_disabled_short_circuits_without_approval(monkeypatch, tmp_path):
    """cfg.computer_use_enabled=False stays at the gate level —
    the disabled refusal happens BEFORE any approval would be
    consulted. Pinned by setting AUTO_DENY and asserting the
    callback was never invoked."""
    monkeypatch.setattr(
        tools_mod, "_load_cfg",
        lambda: _cfg(tmp_path, computer_use_enabled=False),
    )

    callback_calls: list = []

    def _record(tool_name, args):
        callback_calls.append((tool_name, args))
        return "deny"

    token = set_approval_callback(_record)
    try:
        out = json.loads(tools_mod.computer_screenshot())
        assert out["available"] is False
        assert callback_calls == []
    finally:
        reset_approval_callback(token)
