"""T-MIG.2 — url_safety_check @tool tests.

The underlying SSRF defense in athena/safety/url_safety.py
is already tested elsewhere (T1-07-era). These tests focus
on the @tool wrapper's contract:

  - returns valid JSON for the model
  - never raises into the dispatch
  - reflects cfg.url_safety_enabled gate
  - distinguishes safe / blocked-with-reason / unparseable
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest


def _cfg(**overrides: Any) -> SimpleNamespace:
    base = dict(url_safety_enabled=True)
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------
# tool registration
# ---------------------------------------------------------------


def test_url_safety_check_tool_registered():
    import athena.tools  # noqa: F401
    from athena.tools.registry import get_tool
    t = get_tool("url_safety_check")
    assert t is not None
    assert t.toolset == "safety"


def test_tool_schema_requires_url():
    import athena.tools  # noqa: F401
    from athena.tools.registry import get_tool
    t = get_tool("url_safety_check")
    assert t.parameters["required"] == ["url"]


# ---------------------------------------------------------------
# happy paths
# ---------------------------------------------------------------


def test_empty_url_returns_safe_false(monkeypatch):
    monkeypatch.setattr(
        "athena.tools.security.load_config", lambda: _cfg(),
    )
    from athena.tools.security import url_safety_check
    out = json.loads(url_safety_check(url=""))
    assert out["safe"] is False
    assert "no URL" in out["reason"]


def test_disabled_returns_safe_true(monkeypatch):
    """When operator turns off URL safety entirely (e.g. they
    have their own pre-check), the tool short-circuits with
    safe=True + a reason that says checks were skipped."""
    monkeypatch.setattr(
        "athena.tools.security.load_config",
        lambda: _cfg(url_safety_enabled=False),
    )
    from athena.tools.security import url_safety_check
    out = json.loads(url_safety_check(url="http://example.com"))
    assert out["safe"] is True
    assert "skipped" in out["reason"]


def test_validation_failure_returns_safe_false(monkeypatch):
    """When validate_url raises URLSecurityDenied (e.g. private
    IP, blocked scheme), the tool surfaces the deny reason."""
    from athena.safety.url_safety import URLSecurityDenied

    def _denied(_url):
        raise URLSecurityDenied("resolved to private IP 192.168.1.1")

    monkeypatch.setattr(
        "athena.tools.security.load_config", lambda: _cfg(),
    )
    monkeypatch.setattr(
        "athena.safety.url_safety.validate_url", _denied,
    )
    from athena.tools.security import url_safety_check
    out = json.loads(url_safety_check(url="http://10.0.0.1/"))
    assert out["safe"] is False
    assert "private IP" in out["reason"]
    assert out["resolved_ip"] is None


def test_unparseable_url_returns_safe_false(monkeypatch):
    """A non-URLSecurityDenied exception (e.g. ValueError on
    parse failure) is also caught — the tool always returns
    JSON, never raises."""
    monkeypatch.setattr(
        "athena.tools.security.load_config", lambda: _cfg(),
    )

    def _broken(_url):
        raise ValueError("malformed URL")

    monkeypatch.setattr(
        "athena.safety.url_safety.validate_url", _broken,
    )
    from athena.tools.security import url_safety_check
    out = json.loads(url_safety_check(url="not://a/valid/url"))
    assert out["safe"] is False
    assert "validation error" in out["reason"]
    assert "ValueError" in out["reason"]


def test_safe_url_returns_resolved_ip(monkeypatch):
    """Happy path — validate_url returns the resolved IP +
    the tool relays it."""
    import dataclasses
    monkeypatch.setattr(
        "athena.tools.security.load_config", lambda: _cfg(),
    )

    from athena.safety.url_safety import ValidatedURL

    def _ok(_url):
        return ValidatedURL(
            original="https://example.com/path",
            scheme="https",
            host="example.com",
            port=443,
            resolved_ip="93.184.216.34",
            is_ip_literal=False,
        )
    monkeypatch.setattr("athena.safety.url_safety.validate_url", _ok)

    from athena.tools.security import url_safety_check
    out = json.loads(url_safety_check(url="https://example.com/path"))
    assert out["safe"] is True
    assert out["resolved_ip"] == "93.184.216.34"
    assert out["reason"] == "validated"
