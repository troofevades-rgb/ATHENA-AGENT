"""Tests for athena.net.ensure_working_dns_resolver (the aiohttp DNS
resolver fallback). aiohttp is required; skip cleanly without it."""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("aiohttp")

import aiohttp.connector  # noqa: E402
import aiohttp.resolver  # noqa: E402

from athena import net  # noqa: E402

_Async = aiohttp.resolver.AsyncResolver
_Threaded = aiohttp.resolver.ThreadedResolver


@pytest.fixture
def aiodns_default(monkeypatch):
    """Pretend aiodns is the active default in both modules (monkeypatch
    auto-restores the real values after the test)."""
    monkeypatch.setattr(aiohttp.resolver, "DefaultResolver", _Async)
    monkeypatch.setattr(aiohttp.connector, "DefaultResolver", _Async, raising=False)


def test_threaded_mode_forces_threaded(aiodns_default):
    net.ensure_working_dns_resolver("threaded")
    assert aiohttp.resolver.DefaultResolver is _Threaded
    assert aiohttp.connector.DefaultResolver is _Threaded


def test_async_mode_leaves_aiodns(aiodns_default):
    net.ensure_working_dns_resolver("async")
    assert aiohttp.resolver.DefaultResolver is _Async


def test_auto_non_windows_is_noop(aiodns_default, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    # would explode the test if the probe ran; it must NOT on non-Windows
    monkeypatch.setattr(net, "_aiodns_can_resolve", lambda: pytest.fail("probed on non-Windows"))
    net.ensure_working_dns_resolver("auto")
    assert aiohttp.resolver.DefaultResolver is _Async


def test_auto_windows_probe_ok_is_noop(aiodns_default, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(net, "_aiodns_can_resolve", lambda: True)
    net.ensure_working_dns_resolver("auto")
    assert aiohttp.resolver.DefaultResolver is _Async


def test_auto_windows_probe_fails_installs_threaded(aiodns_default, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(net, "_aiodns_can_resolve", lambda: False)
    net.ensure_working_dns_resolver("auto")
    assert aiohttp.resolver.DefaultResolver is _Threaded
    assert aiohttp.connector.DefaultResolver is _Threaded


def test_auto_when_aiodns_absent_is_noop(monkeypatch):
    # aiodns not installed -> default is already ThreadedResolver
    monkeypatch.setattr(aiohttp.resolver, "DefaultResolver", _Threaded)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        net, "_aiodns_can_resolve", lambda: pytest.fail("probed when aiodns absent")
    )
    net.ensure_working_dns_resolver("auto")
    assert aiohttp.resolver.DefaultResolver is _Threaded


def test_unknown_mode_behaves_as_auto(aiodns_default, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    net.ensure_working_dns_resolver("nonsense")  # falls through to auto -> non-win32 no-op
    assert aiohttp.resolver.DefaultResolver is _Async


async def test_probe_skips_inside_running_loop():
    # Inside a running loop the sync probe can't run, so it returns True
    # (assume healthy) rather than false-falling-back.
    assert net._aiodns_can_resolve() is True
