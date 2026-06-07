"""Persistent Playwright context for one athena session (T4-03.2).

The session manager is lazily started — constructing
:class:`BrowserSession` does NOT launch chromium. Only the
first ``ensure_started()`` call does. So a session that never
uses a browser tool pays no chromium cost.

A ContextVar (mirroring T3-03's checkpoint manager pattern)
binds the active session so any tool can reach it without
threading it through every call.

Sync throughout — athena's runtime is sync, so we use
Playwright's ``sync_api``. Spec used ``async_api``; same
adaptation pattern as every other phase.
"""

from __future__ import annotations

import contextvars
import logging
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)


# Set by the Agent at session start; read by the browser tools.
_active_browser: contextvars.ContextVar[BrowserSession | None] = contextvars.ContextVar(
    "athena_browser_session", default=None
)


def get_active_browser() -> BrowserSession | None:
    return _active_browser.get()


def set_active_browser(session: BrowserSession | None) -> None:
    _active_browser.set(session)


class BrowserUnavailable(RuntimeError):
    """Raised when Playwright / chromium isn't installed, or
    when a browser tool is called outside an athena session that
    has set up an active browser."""


def _default_user_agent() -> str:
    """A realistic desktop Chrome UA so legitimate public-target
    research isn't trivially bot-blocked. NOT an evasion tool —
    the capture log makes this an accountability surface."""
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


class BrowserSession:
    """Lazily-launched, persistent Playwright context for one
    athena session. The context's user-data dir lives under
    ``cfg.browser_user_data_root / <session_id>``, isolating
    cookies + storage per session.

    Construct freely (no I/O); the first ``ensure_started()``
    call is what actually launches chromium.
    """

    def __init__(self, *, session_id: str, cfg: Any):
        self.session_id = session_id
        self.cfg = cfg
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def started(self) -> bool:
        return self._context is not None

    def ensure_started(self) -> None:
        """Launch the browser on first use. Idempotent — a second
        call is a no-op (returns the same context)."""
        if self._context is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise BrowserUnavailable(
                "Playwright is not installed. Install with: "
                'pip install -e ".[browser]" && '
                "playwright install chromium"
            ) from e

        self._playwright = sync_playwright().start()
        try:
            user_data_root = Path(
                getattr(self.cfg, "browser_user_data_root", None)
                or (Path.home() / ".athena" / "browser")
            ).expanduser()
            user_data = user_data_root / self.session_id
            user_data.mkdir(parents=True, exist_ok=True)

            headless = bool(getattr(self.cfg, "browser_headless", True))
            block_downloads = bool(getattr(self.cfg, "browser_block_downloads", True))
            user_agent = getattr(self.cfg, "browser_user_agent", None) or _default_user_agent()
            nav_timeout_ms = int(getattr(self.cfg, "browser_nav_timeout_s", 30) * 1000)

            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data),
                headless=headless,
                user_agent=user_agent,
                viewport={"width": 1366, "height": 900},
                locale="en-US",
                accept_downloads=(not block_downloads),
            )
            pages = self._context.pages
            self._page = pages[0] if pages else self._context.new_page()
            self._page.set_default_timeout(nav_timeout_ms)
            logger.info("browser session %s started (headless=%s)", self.session_id, headless)
        except Exception:
            # On any startup failure, tear down the playwright
            # driver so we don't leak a partially-initialised
            # state into the rest of the process.
            with _suppress():
                if self._playwright is not None:
                    self._playwright.stop()
            self._playwright = None
            self._context = None
            self._page = None
            raise

    @property
    def page(self) -> Page:
        """The currently active page. Raises BrowserUnavailable
        if the session hasn't been started yet."""
        if self._page is None:
            raise BrowserUnavailable("browser not started; call ensure_started() first")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise BrowserUnavailable("browser not started; call ensure_started() first")
        return self._context

    def close(self) -> None:
        """Tear down the persistent context. Idempotent."""
        if self._context is not None:
            with _suppress():
                self._context.close()
            self._context = None
        if self._playwright is not None:
            with _suppress():
                self._playwright.stop()
            self._playwright = None
        self._page = None
        logger.info("browser session %s closed", self.session_id)


class _suppress:
    """Tiny context-manager that swallows + debug-logs every
    exception. Used in close paths where one teardown failure
    shouldn't mask another."""

    def __enter__(self) -> _suppress:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc is not None:
            logger.debug("browser teardown leg: %s: %s", exc_type, exc)
        return True
