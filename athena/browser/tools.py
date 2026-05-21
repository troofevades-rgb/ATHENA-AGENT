"""browser_* tool surface (T4-03.4).

Nine model-callable tools:

  browser_navigate(url, wait="load")
  browser_screenshot(full_page=False, selector=None,
                     analyze_prompt=None)
  browser_extract_text(selector=None)
  browser_extract_links()
  browser_click(selector)
  browser_fill(selector, value)
  browser_wait_for(selector, timeout=10)
  browser_get_cookies()
  browser_close()

Every tool:
  - returns JSON (str) so the model can parse it
  - checks ``cfg.browser_enabled`` FIRST — disabled → structured
    "not enabled" payload, NO Playwright contact
  - reads the active BrowserSession from the ContextVar — no
    active session → structured "no active browser" payload
  - lazy-launches chromium on first ensure_started() call
  - on Playwright exception: returns ``{"error": "..."}`` rather
    than raising into the model loop

The screenshot tool optionally routes through vision_analyze
when ``analyze_prompt`` is set — single round-trip "screenshot
+ describe" since most "look at the page and tell me what's
there" workflows want both.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

from ..config import load_config, profile_dir
from ..tools.registry import tool
from .capture import CaptureLogger
from .session import BrowserSession, BrowserUnavailable, get_active_browser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------


def _err(msg: str, **extra: Any) -> str:
    return json.dumps({"error": msg, **extra})


def _ok(**payload: Any) -> str:
    return json.dumps(payload)


def _load_cfg() -> Any:
    """Hook for tests to monkeypatch — returns the live cfg."""
    return load_config()


def _capture_logger_for(cfg: Any) -> CaptureLogger:
    if getattr(cfg, "browser_capture_path", None):
        p = Path(cfg.browser_capture_path)
    else:
        p = profile_dir(getattr(cfg, "profile", "default")) / "browser_capture.jsonl"
    return CaptureLogger(
        p,
        min_interval_s=float(getattr(cfg, "browser_min_interval_s", 1.0)),
    )


def _screenshots_dir(cfg: Any, session_id: str) -> Path:
    if getattr(cfg, "browser_screenshots_dir", None):
        return Path(cfg.browser_screenshots_dir) / session_id
    return profile_dir(getattr(cfg, "profile", "default")) / "browser" / "shots" / session_id


def _gate_or_session() -> tuple[Any, BrowserSession, CaptureLogger] | str:
    """Common pre-flight for every browser tool. Returns
    (cfg, session, capture_logger) on success or a JSON error
    string the tool should return directly."""
    cfg = _load_cfg()
    if not getattr(cfg, "browser_enabled", True):
        return _err(
            "browser_enabled=False; operator has disabled browser tools",
            available=False,
        )
    session = get_active_browser()
    if session is None:
        return _err(
            "no active browser session for this athena session — "
            "the agent runtime hasn't bound a BrowserSession to "
            "this ContextVar yet",
            available=False,
        )
    try:
        session.ensure_started()
    except BrowserUnavailable as e:
        return _err(str(e), available=False)
    return cfg, session, _capture_logger_for(cfg)


def _safe_call(fn, *args, **kw):
    """Run a Playwright call; return a tuple (value, error_str
    or None). Exceptions become structured errors."""
    try:
        return fn(*args, **kw), None
    except Exception as e:  # pragma: no cover - exercised via tests
        logger.warning("browser tool: %s: %s", type(e).__name__, e)
        return None, f"{type(e).__name__}: {e}"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%d_%H%M%S_%f"
    )


# ---------------------------------------------------------------
# browser_navigate
# ---------------------------------------------------------------


@tool(
    name="browser_navigate",
    toolset="browser",
    description=(
        "Navigate the persistent session browser to URL. "
        "Cookies + localStorage from prior tool calls survive. "
        "Per-domain politeness throttle (default 1s) and a "
        "capture log entry land for every navigation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to navigate to."},
            "wait": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle"],
                "description": "Page-load completion signal. Default 'load'.",
            },
        },
        "required": ["url"],
    },
)
def browser_navigate(**kw: Any) -> str:
    gate = _gate_or_session()
    if isinstance(gate, str):
        return gate
    cfg, session, capture = gate
    url = kw.get("url")
    wait = kw.get("wait", "load")
    if not url:
        return _err("url is required")
    capture.throttle(url)
    page = session.page
    resp, err = _safe_call(page.goto, url, wait_until=wait)
    if err:
        return _err(err, url=url)
    title, _ = _safe_call(page.title)
    content, _ = _safe_call(page.content)
    capture.log(
        session_id=session.session_id,
        url=url,
        final_url=page.url,
        status=resp.status if resp else None,
        title=title or "",
        content=content or "",
    )
    return _ok(
        final_url=page.url,
        status=(resp.status if resp else None),
        title=title or "",
    )


# ---------------------------------------------------------------
# browser_screenshot
# ---------------------------------------------------------------


@tool(
    name="browser_screenshot",
    toolset="browser",
    description=(
        "Screenshot the current page; PNG written under the "
        "session's screenshots dir. Optional `selector` "
        "screenshots only that element. Optional `analyze_prompt` "
        "routes the result through vision_analyze describe in "
        "one call — useful for 'read what's on this page'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "full_page": {"type": "boolean", "default": False},
            "selector": {"type": "string"},
            "analyze_prompt": {
                "type": "string",
                "description": (
                    "If set, run vision_analyze describe on the "
                    "screenshot and include the answer in the "
                    "result."
                ),
            },
        },
    },
)
def browser_screenshot(**kw: Any) -> str:
    gate = _gate_or_session()
    if isinstance(gate, str):
        return gate
    cfg, session, _capture = gate
    full_page = bool(kw.get("full_page", False))
    selector = kw.get("selector")
    analyze_prompt = kw.get("analyze_prompt")

    shots_dir = _screenshots_dir(cfg, session.session_id)
    shots_dir.mkdir(parents=True, exist_ok=True)
    out_path = shots_dir / f"shot_{_now_iso()}.png"

    page = session.page
    if selector:
        locator = page.locator(selector)
        _, err = _safe_call(locator.screenshot, path=str(out_path))
    else:
        _, err = _safe_call(page.screenshot, path=str(out_path), full_page=full_page)
    if err:
        return _err(err)

    result: dict[str, Any] = {
        "path": str(out_path),
        "bytes": out_path.stat().st_size,
    }
    if analyze_prompt:
        try:
            from ..vision.analyze import _run as vision_run
            ans_json = vision_run(
                mode="describe",
                path=str(out_path),
                prompt=analyze_prompt,
                _cfg=cfg,
            )
            ans = json.loads(ans_json)
            result["analysis"] = ans.get("answer") or ans.get("error")
        except Exception as e:
            result["analysis_error"] = f"{type(e).__name__}: {e}"
    return _ok(**result)


# ---------------------------------------------------------------
# browser_extract_text / extract_links / extract_html
# ---------------------------------------------------------------


@tool(
    name="browser_extract_text",
    toolset="browser",
    description=(
        "Visible text from the page or a CSS selector. The "
        "page's <body> is the default when no selector given."
    ),
    parameters={
        "type": "object",
        "properties": {"selector": {"type": "string"}},
    },
)
def browser_extract_text(**kw: Any) -> str:
    gate = _gate_or_session()
    if isinstance(gate, str):
        return gate
    cfg, session, _capture = gate
    selector = kw.get("selector")
    page = session.page
    if selector:
        text, err = _safe_call(page.locator(selector).inner_text)
    else:
        text, err = _safe_call(page.inner_text, "body")
    if err:
        return _err(err)
    return _ok(text=text or "", length=len(text or ""))


@tool(
    name="browser_extract_links",
    toolset="browser",
    description=(
        "Every <a href> on the current page as [{href, text}]. "
        "Useful for crawling / scraping link sets."
    ),
    parameters={"type": "object", "properties": {}},
)
def browser_extract_links(**kw: Any) -> str:
    gate = _gate_or_session()
    if isinstance(gate, str):
        return gate
    _cfg, session, _capture = gate
    page = session.page
    links, err = _safe_call(
        page.eval_on_selector_all,
        "a[href]",
        "els => els.map(e => ({href: e.href, text: e.innerText.trim()}))",
    )
    if err:
        return _err(err)
    return _ok(links=links or [], count=len(links or []))


# ---------------------------------------------------------------
# browser_click / fill / wait_for
# ---------------------------------------------------------------


@tool(
    name="browser_click",
    toolset="browser",
    description="Click the element matching the CSS selector.",
    parameters={
        "type": "object",
        "properties": {"selector": {"type": "string"}},
        "required": ["selector"],
    },
)
def browser_click(**kw: Any) -> str:
    gate = _gate_or_session()
    if isinstance(gate, str):
        return gate
    _cfg, session, _capture = gate
    selector = kw.get("selector")
    if not selector:
        return _err("selector is required")
    page = session.page
    _, err = _safe_call(page.locator(selector).click)
    if err:
        return _err(err, selector=selector)
    return _ok(clicked=selector, final_url=page.url)


@tool(
    name="browser_fill",
    toolset="browser",
    description="Fill an input element matched by the selector.",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["selector", "value"],
    },
)
def browser_fill(**kw: Any) -> str:
    gate = _gate_or_session()
    if isinstance(gate, str):
        return gate
    _cfg, session, _capture = gate
    selector = kw.get("selector")
    value = kw.get("value")
    if not selector or value is None:
        return _err("selector and value are required")
    page = session.page
    _, err = _safe_call(page.locator(selector).fill, str(value))
    if err:
        return _err(err, selector=selector)
    return _ok(filled=selector)


@tool(
    name="browser_wait_for",
    toolset="browser",
    description="Wait for a selector to appear (default 10 s).",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string"},
            "timeout": {"type": "integer"},
        },
        "required": ["selector"],
    },
)
def browser_wait_for(**kw: Any) -> str:
    gate = _gate_or_session()
    if isinstance(gate, str):
        return gate
    _cfg, session, _capture = gate
    selector = kw.get("selector")
    timeout = int(kw.get("timeout", 10))
    if not selector:
        return _err("selector is required")
    page = session.page
    _, err = _safe_call(page.locator(selector).wait_for, timeout=timeout * 1000)
    if err:
        return _err(err, selector=selector)
    return _ok(appeared=selector)


# ---------------------------------------------------------------
# browser_get_cookies
# ---------------------------------------------------------------


@tool(
    name="browser_get_cookies",
    toolset="browser",
    description="Get cookies for the current persistent context.",
    parameters={"type": "object", "properties": {}},
)
def browser_get_cookies(**kw: Any) -> str:
    gate = _gate_or_session()
    if isinstance(gate, str):
        return gate
    _cfg, session, _capture = gate
    cookies, err = _safe_call(session.context.cookies)
    if err:
        return _err(err)
    return _ok(cookies=cookies or [], count=len(cookies or []))


# ---------------------------------------------------------------
# browser_close
# ---------------------------------------------------------------


@tool(
    name="browser_close",
    toolset="browser",
    description=(
        "Close the session browser. The persistent user-data "
        "dir stays on disk for a future session resume; only "
        "the live chromium process is torn down."
    ),
    parameters={"type": "object", "properties": {}},
)
def browser_close(**kw: Any) -> str:
    session = get_active_browser()
    if session is None:
        return _ok(closed=False, reason="no active browser")
    session.close()
    return _ok(closed=True)
