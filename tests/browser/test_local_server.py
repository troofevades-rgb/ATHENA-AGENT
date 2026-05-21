"""T4-03.1 — local fixture server sanity tests.

These don't need Playwright. They just confirm the conftest.py
HTTP server serves the documented test content so downstream
browser tests have a stable target.
"""

from __future__ import annotations

import urllib.request


def test_local_server_serves_test_page(local_server: str):
    with urllib.request.urlopen(local_server) as r:
        body = r.read().decode("utf-8")
    assert "<title>Test Page</title>" in body
    assert "Athena Test Page" in body
    assert "page-a" in body and "page-b" in body


def test_local_server_set_cookie_endpoint(local_server: str):
    """The /set-cookie endpoint returns a Set-Cookie header so
    the persistent-context test can prove cookies survive."""
    with urllib.request.urlopen(f"{local_server}/set-cookie") as r:
        cookie = r.headers.get("Set-Cookie", "")
    assert "athena=" in cookie


def test_local_server_page_a(local_server: str):
    with urllib.request.urlopen(f"{local_server}/page-a") as r:
        body = r.read().decode("utf-8")
    assert "Page A" in body
