"""Constant-time webhook authentication.

Two schemes — HMAC-SHA256 over the request body, or Bearer token in
the ``Authorization`` header. Both use :func:`hmac.compare_digest`
to defeat timing attacks; never ``==``.

GitHub-style ``X-Hub-Signature-256: sha256=<hex>`` format is
accepted alongside our own ``X-Webhook-Signature: <hex>`` so the
same webhook URL can serve a GitHub repo and a custom client
without the operator caring.
"""

from __future__ import annotations

import hashlib
import hmac


def verify_hmac_sha256(body: bytes, signature_header: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 verification.

    ``signature_header`` may be ``"sha256=<hex>"`` (GitHub style) or
    a bare ``"<hex>"`` — we strip a leading scheme if present. The
    secret must be the same bytes the sender signed with.
    """
    if not signature_header or not secret:
        return False
    # Strip optional "sha256=" prefix; never trust string slicing
    # against missing values.
    sig = signature_header.split("=", 1)[-1].strip()
    if not sig:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    # Compare hex strings of identical length (hexdigest always
    # returns 64 chars). compare_digest tolerates length mismatch
    # safely (returns False without leaking timing info).
    return hmac.compare_digest(sig, expected)


def verify_bearer(authorization_header: str, expected_token: str) -> bool:
    """Constant-time Bearer-token verification.

    The header must be exactly ``Bearer <token>`` (case-insensitive
    scheme, single space). Missing scheme, wrong scheme, or empty
    token all return False.
    """
    if not authorization_header or not expected_token:
        return False
    parts = authorization_header.split(" ", 1)
    if len(parts) != 2:
        return False
    scheme, value = parts
    if scheme.lower() != "bearer":
        return False
    provided = value.strip()
    if not provided:
        return False
    return hmac.compare_digest(provided, expected_token)
