"""Pinned regression: WebFetch refuses cloud-metadata + private ranges.

The 0.3.0 audit pass initially flagged WebFetch as "no egress filter"
-- that was wrong. ``athena.safety.url_safety`` already blocks every
IP range a model-driven SSRF attempt would reach for, plus runs the
same check on every redirect target via httpx's ``event_hooks``.
This file pins the exact cases the audit claimed were reachable so
a future refactor of ``_BLOCKED_V4`` / ``_BLOCKED_V6`` (or a switch
to a different SSRF library) can't silently re-open them.

The companion suite ``tests/tools/test_web_ssrf.py`` covers the
general behaviour (allow_external_urls override, approval callback,
malformed URL handling); this file is the catastrophic-bypass
regression-pin.

Known gap NOT covered here: DNS rebinding TOCTOU. ``validate_url``
resolves the hostname and verifies every IP is non-blocked, but the
``ValidatedURL.resolved_ip`` it returns is discarded by ``WebFetch``;
httpx then re-resolves the hostname for the actual fetch. An attacker
who controls a domain's DNS can return a safe IP during the validation
step and a blocked IP during the fetch step. Mitigation requires
DNS-pinning at the httpx transport layer (custom HTTPTransport with
SNI override on HTTPS). Tracked as a separate medium-severity finding
-- not the Critical-tier "no filter at all" the audit reported.
"""

from __future__ import annotations

from typing import Any

import pytest

from athena.safety.approval_callback import (
    reset_approval_callback,
    set_approval_callback,
)
from athena.safety.url_safety import URLSecurityDenied, validate_url


@pytest.fixture(autouse=True)
def _deny_by_default():
    """Refuse every approval prompt so blocked URLs raise instead of
    surfacing the interactive callback. The general SSRF tests cover
    the approval path; this file only cares whether the block list
    actually fires."""
    token = set_approval_callback(lambda _tool, _args: "deny")
    try:
        yield
    finally:
        reset_approval_callback(token)


def _fixed_dns(monkeypatch: pytest.MonkeyPatch, host: str, ip: str) -> None:
    """Pin DNS resolution for ``host`` -> single ``ip``. Bypasses real
    network access for hostname cases."""
    import socket as _sock

    from athena.safety import url_safety as _us

    def _fake(h: str, *_a: Any, **_kw: Any) -> list:
        if h == host:
            family = _sock.AF_INET6 if ":" in ip else _sock.AF_INET
            return [(family, _sock.SOCK_STREAM, 0, "", (ip, 0))]
        raise _sock.gaierror(f"no fake DNS for {h}")

    monkeypatch.setattr(_us.socket, "getaddrinfo", _fake)


# ---------------------------------------------------------------------------
# Cloud metadata endpoints (the audit's headline claim)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        # AWS / Azure / DigitalOcean / OpenStack IMDS (IPv4)
        "http://169.254.169.254/",
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254/latest/dynamic/instance-identity/document",
        # GCP metadata server (uses 169.254.169.254 by default)
        "http://metadata.google.internal/computeMetadata/v1/",
        # AWS IMDSv2 IPv6 endpoint
        "http://[fd00:ec2::254]/latest/meta-data/",
    ],
)
def test_cloud_metadata_endpoints_blocked_by_ip(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single-most exploitable SSRF target. If any of these are
    ever reachable, an agent running on cloud spits out IAM creds /
    project metadata / service account tokens with one model
    prompt."""
    # metadata.google.internal -> 169.254.169.254 in real DNS.
    _fixed_dns(monkeypatch, "metadata.google.internal", "169.254.169.254")
    with pytest.raises(URLSecurityDenied):
        validate_url(url)


# ---------------------------------------------------------------------------
# Loopback / link-local
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/admin",
        "http://127.255.255.254/",  # high end of 127/8
        "http://[::1]/",  # IPv6 loopback
        "http://[fe80::1]/link-local",  # IPv6 link-local
    ],
)
def test_loopback_and_link_local_blocked(url: str) -> None:
    with pytest.raises(URLSecurityDenied):
        validate_url(url)


# ---------------------------------------------------------------------------
# RFC1918 (and equivalents)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.1/",
        "http://10.255.255.254/",
        "http://172.16.0.1/",
        "http://172.31.255.254/",
        "http://192.168.0.1/",
        "http://192.168.255.254/",
        # Carrier-grade NAT (where AWS metadata used to live on EKS)
        "http://100.64.0.1/",
        # IPv6 unique-local (RFC4193)
        "http://[fc00::1]/",
        "http://[fdaa:bbcc::1]/",
    ],
)
def test_private_network_ranges_blocked(url: str) -> None:
    with pytest.raises(URLSecurityDenied):
        validate_url(url)


# ---------------------------------------------------------------------------
# Hostname resolving to a blocked IP (the realistic exploit shape)
# ---------------------------------------------------------------------------


def test_attacker_hostname_resolving_to_metadata_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Realistic attack shape: attacker registers a domain whose DNS
    points to 169.254.169.254 and tells the user "summarise this URL"
    -- without IP-level blocking, the egress filter would only catch
    bare IPs."""
    _fixed_dns(monkeypatch, "evil.attacker.example", "169.254.169.254")
    with pytest.raises(URLSecurityDenied):
        validate_url("https://evil.attacker.example/innocent-path")


def test_attacker_hostname_resolving_to_localhost_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same vector pointed at an internal service rather than cloud
    metadata."""
    _fixed_dns(monkeypatch, "lol.attacker.example", "127.0.0.1")
    with pytest.raises(URLSecurityDenied):
        validate_url("https://lol.attacker.example/")


# ---------------------------------------------------------------------------
# Scheme + format guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://evil.example/",
        "ftp://evil.example/",
        "ldap://internal/",
    ],
)
def test_non_http_schemes_blocked(url: str) -> None:
    """Non-http(s) schemes are refused outright -- no chance to
    resolve and exfil via gopher/file/etc."""
    with pytest.raises(URLSecurityDenied):
        validate_url(url)


def test_empty_hostname_blocked() -> None:
    """``http://?key=x`` parses to an empty hostname -- refuse rather
    than letting httpx's default-server-name handling pick something."""
    with pytest.raises(URLSecurityDenied):
        validate_url("http://?key=x")
