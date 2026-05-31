"""HMAC and Bearer verification — constant-time."""

from __future__ import annotations

import hashlib
import hmac

from athena.webhooks.auth import verify_bearer, verify_hmac_sha256

# ---- HMAC -----------------------------------------------------------


def _sig(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_hmac_correct_bare_hex() -> None:
    body = b'{"event":"push"}'
    sig = _sig(body, "s3cret")
    assert verify_hmac_sha256(body, sig, "s3cret") is True


def test_hmac_correct_with_sha256_prefix() -> None:
    """GitHub sends X-Hub-Signature-256: sha256=<hex>."""
    body = b"{}"
    sig = "sha256=" + _sig(body, "github-secret")
    assert verify_hmac_sha256(body, sig, "github-secret") is True


def test_hmac_wrong_signature() -> None:
    body = b"hello"
    bad = "a" * 64
    assert verify_hmac_sha256(body, bad, "secret") is False


def test_hmac_wrong_secret() -> None:
    body = b"hello"
    sig = _sig(body, "right-secret")
    assert verify_hmac_sha256(body, sig, "wrong-secret") is False


def test_hmac_modified_body_fails() -> None:
    """Same secret, different body → fail (sig was for the original body)."""
    sig = _sig(b"original", "s")
    assert verify_hmac_sha256(b"tampered", sig, "s") is False


def test_hmac_empty_signature() -> None:
    assert verify_hmac_sha256(b"body", "", "secret") is False


def test_hmac_empty_secret() -> None:
    assert verify_hmac_sha256(b"body", "deadbeef", "") is False


def test_hmac_prefix_only() -> None:
    """Just 'sha256=' with no hex after."""
    assert verify_hmac_sha256(b"body", "sha256=", "secret") is False


def test_hmac_empty_body() -> None:
    """Some webhooks fire with no body (e.g. ping)."""
    sig = _sig(b"", "s")
    assert verify_hmac_sha256(b"", sig, "s") is True


def test_hmac_case_matters() -> None:
    """Hex digits are lowercase per Python's hexdigest; uppercase
    fails constant-time compare (which is fine — senders should send
    lowercase). Documents the contract."""
    body = b"x"
    sig = _sig(body, "s")
    assert verify_hmac_sha256(body, sig.upper(), "s") is False


# ---- Bearer ---------------------------------------------------------


def test_bearer_correct_token() -> None:
    assert verify_bearer("Bearer my-token", "my-token") is True


def test_bearer_case_insensitive_scheme() -> None:
    """RFC 7235 says the scheme is case-insensitive."""
    assert verify_bearer("bearer my-token", "my-token") is True
    assert verify_bearer("BEARER my-token", "my-token") is True


def test_bearer_wrong_token() -> None:
    assert verify_bearer("Bearer wrong", "my-token") is False


def test_bearer_missing_scheme() -> None:
    """Just a bare token without the 'Bearer ' prefix."""
    assert verify_bearer("my-token", "my-token") is False


def test_bearer_wrong_scheme() -> None:
    assert verify_bearer("Basic dXNlcjpwYXNz", "my-token") is False


def test_bearer_empty_token_in_header() -> None:
    assert verify_bearer("Bearer ", "my-token") is False
    assert verify_bearer("Bearer    ", "my-token") is False


def test_bearer_empty_expected() -> None:
    assert verify_bearer("Bearer x", "") is False


def test_bearer_empty_header() -> None:
    assert verify_bearer("", "my-token") is False


def test_bearer_trailing_whitespace_is_significant() -> None:
    """Byte-for-byte equality only -- the previous implementation
    called .strip() on the value, which masked operator config bugs
    (if the stored expected_token had accidental trailing whitespace
    the comparison still succeeded, so the operator never saw the
    config mistake). Post-fix: whitespace counts as part of the
    token."""
    # Header has trailing whitespace; expected does NOT.
    assert verify_bearer("Bearer my-token   ", "my-token") is False
    # Header is clean; expected has trailing whitespace.
    assert verify_bearer("Bearer my-token", "my-token   ") is False
    # Both have matching trailing whitespace -- bytes are equal,
    # comparison succeeds. (Not recommended config, but the result
    # is at least consistent and lets the operator see what they
    # actually wrote.)
    assert verify_bearer("Bearer my-token  ", "my-token  ") is True
