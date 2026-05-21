"""Shared fixtures for browser tests (T4-03.1).

A tiny local HTTP server serves a static HTML test page so we
don't hit the live internet from CI. Yields the URL.

Browser tests gate on ``_playwright_available()`` — when
Playwright (or its chromium binary) isn't installed they skip
cleanly.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterator

import pytest


_TEST_HTML = b"""<!doctype html>
<html lang="en">
<head><title>Test Page</title></head>
<body>
  <h1>Athena Test Page</h1>
  <p id="intro">A small fixture page for browser tests.</p>
  <ul>
    <li><a href="/page-a">page-a</a></li>
    <li><a href="/page-b">page-b</a></li>
    <li><a href="https://example.com/external">external</a></li>
  </ul>
  <form id="f" method="get" action="/echo">
    <input id="q" name="q" type="text" />
    <button id="go" type="submit">Submit</button>
  </form>
  <div id="hidden">target-text</div>
</body>
</html>
"""

_COOKIE_HTML = b"""<!doctype html>
<html><head><title>Cookie Set</title></head>
<body><p>cookie set</p></body></html>
"""

_PAGE_A = b"<!doctype html><html><head><title>Page A</title></head><body><h1>A</h1></body></html>"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args, **_kwargs):  # quiet
        pass

    def do_GET(self):  # noqa: N802 — http.server hook
        if self.path.startswith("/set-cookie"):
            self.send_response(200)
            self.send_header("Set-Cookie", "athena=ok; Path=/")
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(_COOKIE_HTML)
            return
        if self.path.startswith("/page-a"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(_PAGE_A)
            return
        # Default → the index page.
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(_TEST_HTML)


def _playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        return False
    return True


@pytest.fixture
def local_server() -> Iterator[str]:
    """Start an ephemeral-port HTTP server. Yields its base URL."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture(scope="session")
def have_playwright() -> bool:
    return _playwright_available()
