"""T4-03.5 — Agent ↔ BrowserSession lifecycle tests.

The agent runtime is what binds a BrowserSession to the
ContextVar at session start + tears it down at session end.
These tests pin that wiring without launching chromium — we
check the ContextVar is bound + .browser_session attribute is
set + close() releases it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from athena.browser.session import (
    BrowserSession, get_active_browser, set_active_browser,
)


# ---------------------------------------------------------------
# Lazy launch — Agent binds, doesn't launch chromium
# ---------------------------------------------------------------


def test_browser_session_is_lazy_by_construction(tmp_path: Path):
    """Constructing a BrowserSession with no ensure_started
    call must NEVER launch chromium. The whole point of T4-03.5
    is the agent binds a session-scoped BrowserSession at
    startup — and that binding must be free of cost when no
    browser tool is ever called."""
    cfg = SimpleNamespace(
        browser_enabled=True,
        browser_headless=True,
        browser_user_data_root=str(tmp_path / "ud"),
        browser_nav_timeout_s=30,
        browser_block_downloads=True,
        browser_user_agent=None,
    )
    sess = BrowserSession(session_id="lifecycle-1", cfg=cfg)
    # No chromium launched yet.
    assert sess.started is False
    # And after close() (a no-op for a never-started session) it
    # is still not started.
    sess.close()
    assert sess.started is False


def test_set_active_then_clear(tmp_path: Path):
    """The agent runtime sets, runs, then clears — proven
    here without touching the full Agent class."""
    cfg = SimpleNamespace(
        browser_enabled=True, browser_headless=True,
        browser_user_data_root=str(tmp_path / "ud"),
        browser_nav_timeout_s=30, browser_block_downloads=True,
        browser_user_agent=None,
    )
    sess = BrowserSession(session_id="lc-2", cfg=cfg)
    set_active_browser(sess)
    assert get_active_browser() is sess
    set_active_browser(None)
    assert get_active_browser() is None


# ---------------------------------------------------------------
# Tools see the bound session (no chromium needed)
# ---------------------------------------------------------------


def test_tools_see_session_via_contextvar(tmp_path: Path, monkeypatch):
    """Without a real browser, prove the gate function picks up
    the session from the ContextVar — the only branch that
    matters before ensure_started fires."""
    import json
    from athena.browser import tools as bt

    cfg = SimpleNamespace(
        profile="default",
        browser_enabled=True,
        browser_headless=True,
        browser_user_data_root=str(tmp_path / "ud"),
        browser_capture_path=str(tmp_path / "c.jsonl"),
        browser_screenshots_dir=str(tmp_path / "s"),
        browser_nav_timeout_s=30,
        browser_min_interval_s=0,
        browser_block_downloads=True,
        browser_user_agent=None,
        vision_enabled=False,
    )
    monkeypatch.setattr(bt, "_load_cfg", lambda: cfg)
    sess = BrowserSession(session_id="lc-3", cfg=cfg)
    set_active_browser(sess)
    try:
        # Patch ensure_started to no-op + bake a page-like object
        # so the gate doesn't actually try to launch chromium.
        sess.ensure_started = lambda: None
        sess._page = object()  # type: ignore[attr-defined]
        # The url-required branch fires when no url passed —
        # this proves the gate ALLOWED us through (no
        # browser_enabled / no-session error).
        out = json.loads(bt.browser_navigate())
        assert "error" in out
        assert "url is required" in out["error"]
    finally:
        set_active_browser(None)


# ---------------------------------------------------------------
# Agent integration — light-weight (don't construct full Agent
# because of heavy deps; verify the bind/teardown contract
# directly on BrowserSession with set_active_browser)
# ---------------------------------------------------------------


def test_unused_browser_never_launches(tmp_path: Path):
    """Construct BrowserSession + immediately close. The
    persistent-context launch path must never have fired.

    Implementation detail check: BrowserSession.started stays
    False the whole time — that flips True only inside
    ensure_started's launch_persistent_context call."""
    cfg = SimpleNamespace(
        browser_enabled=True, browser_headless=True,
        browser_user_data_root=str(tmp_path / "ud"),
        browser_nav_timeout_s=30, browser_block_downloads=True,
        browser_user_agent=None,
    )

    with patch(
        "athena.browser.session.sync_playwright",
        side_effect=AssertionError("ensure_started must NOT fire"),
        create=True,
    ):
        sess = BrowserSession(session_id="unused", cfg=cfg)
        set_active_browser(sess)
        # … the agent runs, never calls a browser_* tool …
        set_active_browser(None)
        sess.close()  # close on an unused session must be a no-op


def test_close_is_idempotent_on_lifecycle(tmp_path: Path):
    cfg = SimpleNamespace(
        browser_enabled=True, browser_headless=True,
        browser_user_data_root=str(tmp_path / "ud"),
        browser_nav_timeout_s=30, browser_block_downloads=True,
        browser_user_agent=None,
    )
    sess = BrowserSession(session_id="lc-close", cfg=cfg)
    sess.close()
    sess.close()  # safe to call again
    sess.close()
