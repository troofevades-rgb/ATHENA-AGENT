"""T4-03.4 — browser_* tool surface tests.

Mix of always-running tests (gate + no-active-session paths)
and live-browser tests (full navigate / persistent cookies /
screenshot / extract).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.browser import tools as bt
from athena.browser.session import (
    BrowserSession, get_active_browser, set_active_browser,
)


def _cfg(tmp_path: Path, **overrides):
    base = dict(
        profile="default",
        browser_enabled=True,
        browser_headless=True,
        browser_user_data_root=str(tmp_path / "ud"),
        browser_capture_path=str(tmp_path / "capture.jsonl"),
        browser_screenshots_dir=str(tmp_path / "shots"),
        browser_nav_timeout_s=30,
        browser_min_interval_s=0,  # disable throttle in tests for speed
        browser_block_downloads=True,
        browser_user_agent=None,
        vision_enabled=False,  # off by default in tests
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------
# Always-running gate + no-session paths
# ---------------------------------------------------------------


def test_navigate_refuses_when_browser_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(bt, "_load_cfg", lambda: _cfg(tmp_path, browser_enabled=False))
    set_active_browser(None)
    out = json.loads(bt.browser_navigate(url="https://example.com/"))
    assert "error" in out
    assert "browser_enabled=False" in out["error"]


def test_navigate_refuses_when_no_active_session(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(bt, "_load_cfg", lambda: _cfg(tmp_path))
    set_active_browser(None)
    out = json.loads(bt.browser_navigate(url="https://example.com/"))
    assert "error" in out
    assert "no active browser session" in out["error"]


def test_navigate_missing_url(tmp_path: Path, monkeypatch):
    """Live session bound but no url arg → clear error."""
    monkeypatch.setattr(bt, "_load_cfg", lambda: _cfg(tmp_path))
    # Bind a session that wouldn't even launch (we don't reach
    # ensure_started — the url-required check fires first).
    sess = BrowserSession(session_id="t", cfg=_cfg(tmp_path))
    set_active_browser(sess)
    try:
        # Since gate() calls ensure_started(), we need to skip
        # past the gate. Easier: directly assert through the
        # gate function semantics: an enabled session with no
        # active browser is the more useful no-session test.
        # This test just confirms missing url is rejected; we
        # mock ensure_started to no-op.
        sess.ensure_started = lambda: None
        sess._page = object()  # type: ignore
        out = json.loads(bt.browser_navigate())
        assert "error" in out
        assert "url is required" in out["error"]
    finally:
        set_active_browser(None)


def test_close_with_no_active_session_returns_no_op(tmp_path: Path, monkeypatch):
    set_active_browser(None)
    out = json.loads(bt.browser_close())
    assert out["closed"] is False
    assert "no active browser" in out["reason"]


# ---------------------------------------------------------------
# Live browser — full integration
# ---------------------------------------------------------------


def _playwright_with_chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            _ = p.chromium
        return True
    except Exception:
        return False


_NEED_BROWSER = pytest.mark.skipif(
    not _playwright_with_chromium(),
    reason="Playwright + chromium not available",
)


@pytest.fixture
def active_session(tmp_path: Path, monkeypatch):
    """Bind a real BrowserSession to the ContextVar for the test."""
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(bt, "_load_cfg", lambda: cfg)
    sess = BrowserSession(session_id="test-session", cfg=cfg)
    set_active_browser(sess)
    try:
        yield sess
    finally:
        sess.close()
        set_active_browser(None)


@_NEED_BROWSER
def test_navigate_returns_title(active_session, local_server):
    out = json.loads(bt.browser_navigate(url=local_server))
    assert "Test Page" in out["title"]
    assert out["status"] == 200
    assert out["final_url"].startswith("http://127.0.0.1:")


@_NEED_BROWSER
def test_persistent_context_keeps_cookies_across_calls(
    active_session, local_server, tmp_path: Path,
):
    """THE load-bearing test for T4-03: a cookie set on one
    navigation survives across the next."""
    bt.browser_navigate(url=f"{local_server}/set-cookie")
    cookies_1 = json.loads(bt.browser_get_cookies())
    assert cookies_1["count"] >= 1
    cookie_names = {c.get("name") for c in cookies_1["cookies"]}
    assert "athena" in cookie_names
    # Navigate elsewhere; cookie should still be there.
    bt.browser_navigate(url=f"{local_server}/page-a")
    cookies_2 = json.loads(bt.browser_get_cookies())
    cookie_names_2 = {c.get("name") for c in cookies_2["cookies"]}
    assert "athena" in cookie_names_2


@_NEED_BROWSER
def test_extract_text_returns_body(active_session, local_server):
    bt.browser_navigate(url=local_server)
    out = json.loads(bt.browser_extract_text())
    assert "Athena Test Page" in out["text"]


@_NEED_BROWSER
def test_extract_links_finds_all(active_session, local_server):
    bt.browser_navigate(url=local_server)
    out = json.loads(bt.browser_extract_links())
    assert out["count"] >= 3
    hrefs = {l["href"] for l in out["links"]}
    assert any("page-a" in h for h in hrefs)
    assert any("page-b" in h for h in hrefs)


@_NEED_BROWSER
def test_screenshot_writes_file(active_session, local_server, tmp_path: Path):
    bt.browser_navigate(url=local_server)
    out = json.loads(bt.browser_screenshot())
    p = Path(out["path"])
    assert p.exists()
    assert p.stat().st_size > 0


@_NEED_BROWSER
def test_screenshot_analyze_routes_to_vision(
    active_session, local_server, tmp_path: Path, monkeypatch,
):
    """analyze_prompt → calls vision_analyze describe. Stub the
    vision module to confirm the prompt + path were passed."""
    bt.browser_navigate(url=local_server)

    seen: dict = {}
    def _stub_run(*, mode, path, prompt, _cfg, **_):
        seen["mode"] = mode
        seen["path"] = path
        seen["prompt"] = prompt
        return json.dumps({"answer": "stub described the page"})

    import sys
    import types
    fake_mod = types.ModuleType("athena.vision.analyze")
    fake_mod._run = _stub_run
    monkeypatch.setitem(sys.modules, "athena.vision.analyze", fake_mod)

    out = json.loads(bt.browser_screenshot(analyze_prompt="what's here?"))
    assert "analysis" in out
    assert out["analysis"] == "stub described the page"
    assert seen["mode"] == "describe"
    assert seen["prompt"] == "what's here?"


@_NEED_BROWSER
def test_fill_and_click(active_session, local_server):
    bt.browser_navigate(url=local_server)
    fill_out = json.loads(bt.browser_fill(selector="#q", value="hello"))
    assert fill_out["filled"] == "#q"
    click_out = json.loads(bt.browser_click(selector="#go"))
    assert click_out["clicked"] == "#go"
    # Submitting the form lands somewhere — final_url changed
    assert "/echo" in click_out["final_url"] or "?" in click_out["final_url"]


@_NEED_BROWSER
def test_navigate_logs_capture_entry(active_session, local_server, tmp_path: Path):
    bt.browser_navigate(url=local_server)
    raw = (tmp_path / "capture.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(l) for l in raw.splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["session_id"] == "test-session"
    assert rows[0]["status"] == 200
    assert rows[0]["title"] == "Test Page"
    assert len(rows[0]["content_sha256"]) == 64


# ---------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------


def test_all_browser_tools_registered():
    import athena.tools  # noqa: F401 — trigger registration
    from athena.tools.registry import all_tools
    names = {t.name for t in all_tools()}
    for n in (
        "browser_navigate", "browser_screenshot", "browser_extract_text",
        "browser_extract_links", "browser_click", "browser_fill",
        "browser_wait_for", "browser_get_cookies", "browser_close",
    ):
        assert n in names, f"missing tool: {n}"


def test_browser_tools_in_browser_toolset():
    import athena.tools  # noqa: F401
    from athena.tools.registry import get_tool
    for n in ("browser_navigate", "browser_screenshot",
              "browser_extract_text", "browser_click"):
        t = get_tool(n)
        assert t.toolset == "browser"
