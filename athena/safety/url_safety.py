"""SSRF defense for the web tool.

Every URL fetched by ``athena/tools/web.py`` is validated through
``validate_url``. The validator:

1. Parses the URL and checks the scheme is http or https.
2. Resolves the hostname to one or more IP addresses.
3. Checks every resolved IP against block lists for RFC1918,
   loopback, link-local, carrier-grade NAT, IPv6 ULA, cloud
   metadata endpoints, and multicast.
4. If any resolved IP is blocked, denies the URL — unless the
   active approval callback overrides AND the user is in a foreground
   session.
5. Returns a ValidatedURL containing the original URL plus the
   first non-blocked resolved IP. The caller fetches by the IP
   directly to avoid DNS rebinding.

Public surface:
    validate_url(url) -> ValidatedURL
    allow_external_urls() -> context manager
    URLSecurityDenied

The approval callback signature follows the rest of the project:
``(tool_name, args) -> "allow"|"deny"``.
"""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import ipaddress
import json
import logging
import socket
import urllib.parse
from collections.abc import Iterator, Sequence
from typing import Any

from .approval_callback import get_approval_callback

logger = logging.getLogger(__name__)


class URLSecurityDenied(PermissionError):
    """Raised when a URL fetch is refused."""


_BLOCKED_V4: tuple[ipaddress.IPv4Network, ...] = tuple(
    ipaddress.IPv4Network(n)
    for n in (
        "0.0.0.0/8",  # unspecified
        "10.0.0.0/8",  # RFC1918
        "100.64.0.0/10",  # carrier-grade NAT (cloud metadata fallback)
        "127.0.0.0/8",  # loopback
        "169.254.0.0/16",  # link-local AND cloud metadata
        "172.16.0.0/12",  # RFC1918
        "192.0.0.0/24",  # IETF protocol assignments
        "192.0.2.0/24",  # documentation (TEST-NET-1)
        "192.168.0.0/16",  # RFC1918
        "198.18.0.0/15",  # benchmark testing
        "198.51.100.0/24",  # documentation (TEST-NET-2)
        "203.0.113.0/24",  # documentation (TEST-NET-3)
        "224.0.0.0/4",  # multicast
        "240.0.0.0/4",  # reserved
        "255.255.255.255/32",  # broadcast
    )
)

_BLOCKED_V6: tuple[ipaddress.IPv6Network, ...] = tuple(
    ipaddress.IPv6Network(n)
    for n in (
        "::/128",  # unspecified
        "::1/128",  # loopback
        "64:ff9b::/96",  # IPv4/IPv6 translation
        "100::/64",  # discard
        "fc00::/7",  # unique local (ULA)
        "fe80::/10",  # link-local
        "fd00:ec2::254/128",  # AWS IMDSv2 IPv6 metadata
        "ff00::/8",  # multicast
    )
)


_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})


_allow_external_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "athena_url_security_allow_external_depth", default=0
)


@contextlib.contextmanager
def allow_external_urls() -> Iterator[None]:
    """Suppress the SSRF approval prompt for the current block.

    Use for tests that legitimately fetch from localhost (test
    servers) or for foreground tool implementations where the user
    explicitly supplied a private URL via the CLI.

    Even within this context manager, the block lists still emit
    audit-log entries for the bypass.
    """
    token = _allow_external_depth.set(_allow_external_depth.get() + 1)
    try:
        yield
    finally:
        _allow_external_depth.reset(token)


@dataclasses.dataclass(frozen=True)
class ValidatedURL:
    """Result of validate_url.

    The caller should fetch using ``resolved_ip`` (with a ``Host``
    header equal to ``host``) to defeat DNS rebinding between the
    validation step and the actual fetch.
    """

    original: str
    scheme: str
    host: str
    port: int
    resolved_ip: str
    is_ip_literal: bool


def _is_blocked_v4(ip: ipaddress.IPv4Address) -> bool:
    return any(ip in net for net in _BLOCKED_V4)


def _is_blocked_v6(ip: ipaddress.IPv6Address) -> bool:
    if ip.ipv4_mapped is not None:
        return _is_blocked_v4(ip.ipv4_mapped)
    return any(ip in net for net in _BLOCKED_V6)


def _is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        # Unparseable -> fail-closed.
        return True
    if isinstance(ip, ipaddress.IPv4Address):
        return _is_blocked_v4(ip)
    return _is_blocked_v6(ip)


def _resolve_all(host: str) -> Sequence[str]:
    """Resolve ``host`` to all IP addresses (IPv4 and IPv6)."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise URLSecurityDenied(f"DNS resolution failed for {host!r}: {exc}") from exc
    return tuple({info[4][0] for info in infos})


def audit_append(*, kind: str, payload: dict[str, Any]) -> None:
    """Record a URL-safety policy event.

    Thin shim over ``logger.warning`` with a grep-able structured
    prefix. Tests monkeypatch this name to capture calls.
    """
    logger.warning(
        "url_safety %s %s",
        kind,
        json.dumps(payload, separators=(",", ":")),
    )


def validate_url(url: str) -> ValidatedURL:
    """Validate ``url`` for SSRF safety.

    Returns ``ValidatedURL`` on success. Raises ``URLSecurityDenied`` if:
    - The URL is malformed or empty.
    - The scheme is not http/https.
    - The host resolves to a blocked IP and approval is denied (or the
      callback returns anything other than ``"allow"``).
    """
    parsed = urllib.parse.urlsplit(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise URLSecurityDenied(
            f"Refusing URL with scheme {parsed.scheme!r}: only http/https allowed. "
            f"(URL: {url})"
        )

    host = parsed.hostname
    if not host:
        raise URLSecurityDenied(f"Refusing URL with empty hostname: {url}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        ip = ipaddress.ip_address(host)
        is_ip_literal = True
        resolved_ips: Sequence[str] = (str(ip),)
    except ValueError:
        is_ip_literal = False
        resolved_ips = _resolve_all(host)

    blocked_ips = [rip for rip in resolved_ips if _is_blocked(rip)]

    if blocked_ips:
        if _allow_external_depth.get() > 0:
            audit_append(
                kind="url_security_allow_external_bypass",
                payload={"url": url, "blocked_ips": list(blocked_ips)},
            )
            return ValidatedURL(
                original=url,
                scheme=parsed.scheme,
                host=host,
                port=port,
                resolved_ip=resolved_ips[0],
                is_ip_literal=is_ip_literal,
            )

        callback = get_approval_callback()
        args = {
            "url": url,
            "resolved_ips": list(resolved_ips),
            "blocked_ips": list(blocked_ips),
        }
        decision = callback("url_safety", args)
        if decision != "allow":
            raise URLSecurityDenied(
                f"Refusing fetch of {url}: resolves to blocked IP(s) "
                f"{', '.join(blocked_ips)} (likely SSRF). "
                "If this is a legitimate internal URL, use "
                "`allow_external_urls()` in a test, or approve at the "
                "prompt in a foreground session."
            )

        audit_append(
            kind="url_security_approval",
            payload={"url": url, "approved_ips": list(blocked_ips)},
        )

    return ValidatedURL(
        original=url,
        scheme=parsed.scheme,
        host=host,
        port=port,
        resolved_ip=resolved_ips[0],
        is_ip_literal=is_ip_literal,
    )
