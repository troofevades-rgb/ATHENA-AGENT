"""T4-03.2 — persistent session manager tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from athena.browser.session import (
    BrowserSession,
    BrowserUnavailable,
    get_active_browser,
    set_active_browser,
)


def _cfg(tmp_path: Path, **overrides):
    base = dict(
        browser_headless=True,
        browser_user_data_root=str(tmp_path / "ud"),
        browser_user_agent=None,
        browser_nav_timeout_s=30,
        browser_block_downloads=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------
# ContextVar + lazy-launch (no Playwright needed)
# ---------------------------------------------------------------


def test_get_active_browser_none_by_default():
    """A fresh session context has no active browser; tools
    must surface a clear unavailable error rather than crash."""
    # set to None to ensure fresh state on this test thread
    set_active_browser(None)
    assert get_active_browser() is None


def test_set_and_get_round_trip(tmp_path: Path):
    sess = BrowserSession(session_id="t", cfg=_cfg(tmp_path))
    set_active_browser(sess)
    assert get_active_browser() is sess
    set_active_browser(None)


def test_session_constructor_does_not_launch(tmp_path: Path):
    """Constructing BrowserSession must NOT touch chromium.
    The whole point of lazy-launch is that an unused browser
    costs nothing."""
    sess = BrowserSession(session_id="t", cfg=_cfg(tmp_path))
    assert sess.started is False
    # Accessing .page before ensure_started → clear unavailable error
    with pytest.raises(BrowserUnavailable):
        _ = sess.page


def test_unavailable_when_playwright_absent(tmp_path: Path):
    """Force the playwright import to raise; ensure_started
    surfaces a clear install hint, never crashes mysteriously."""
    sess = BrowserSession(session_id="t", cfg=_cfg(tmp_path))

    def _raise_import(*_a, **_kw):
        raise ImportError("no module named playwright")

    with patch("athena.browser.session.sync_playwright",
               side_effect=_raise_import, create=True):
        # Some Python builds raise at the from-import site;
        # mock the imported symbol when it exists, and the
        # ImportError reaches ensure_started either way.
        try:
            from playwright import sync_api  # noqa: F401
            playwright_installed = True
        except Exception:
            playwright_installed = False

        if not playwright_installed:
            with pytest.raises(BrowserUnavailable, match="Playwright is not installed"):
                sess.ensure_started()
        else:
            # Patch the local import inside ensure_started by
            # monkeypatching sys.modules
            import sys
            orig = sys.modules.get("playwright.sync_api")
            sys.modules["playwright.sync_api"] = None  # ImportError on import
            try:
                with pytest.raises(BrowserUnavailable):
                    sess.ensure_started()
            finally:
                if orig is not None:
                    sys.modules["playwright.sync_api"] = orig
                else:
                    sys.modules.pop("playwright.sync_api", None)


# ---------------------------------------------------------------
# Live launch (needs Playwright + chromium)
# ---------------------------------------------------------------


def _playwright_with_chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            # Lazy attribute check — touches the chromium descriptor
            _ = p.chromium
        return True
    except Exception:
        return False


_NEED_BROWSER = pytest.mark.skipif(
    not _playwright_with_chromium(),
    reason="Playwright + chromium not available",
)


@_NEED_BROWSER
def test_ensure_started_is_idempotent(tmp_path: Path):
    sess = BrowserSession(session_id="t1", cfg=_cfg(tmp_path))
    try:
        sess.ensure_started()
        assert sess.started is True
        ctx_1 = sess.context
        sess.ensure_started()  # second call no-ops
        assert sess.context is ctx_1
    finally:
        sess.close()


@_NEED_BROWSER
def test_ensure_started_creates_user_data_dir(tmp_path: Path):
    sess = BrowserSession(session_id="ud-test", cfg=_cfg(tmp_path))
    try:
        sess.ensure_started()
        user_dir = tmp_path / "ud" / "ud-test"
        assert user_dir.exists()
    finally:
        sess.close()


@_NEED_BROWSER
def test_close_releases_resources(tmp_path: Path):
    sess = BrowserSession(session_id="close-test", cfg=_cfg(tmp_path))
    sess.ensure_started()
    assert sess.started is True
    sess.close()
    assert sess.started is False
    # Second close is idempotent — must not raise
    sess.close()
