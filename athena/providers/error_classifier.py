"""API error classification for smart failover and recovery.

Provides a structured taxonomy of API errors and a priority-ordered
classification pipeline that determines the correct recovery action
for each error.

The classifier is pure: given an exception object (and optional
HTTP context), returns a ``Classification``. No I/O, no retries —
those live in ``retry_utils``.

Classification priority order (first match wins):

  1. Network-layer errors (DNS, TCP, TLS) -> RETRY
  2. Client-side timeouts -> RETRY
  3. HTTP 429 -> RETRY (with optional Retry-After backoff)
  4. HTTP 408 -> RETRY
  5. HTTP 5xx -> RETRY (or COMPRESS_CONTEXT if body matches)
  6. HTTP 400 with a context-length message -> COMPRESS_CONTEXT
  7. HTTP 4xx other -> ABORT
  8. Stream / read error -> RETRY
  9. JSON parse error -> RETRY
  10. Bare exception text matching a context-length pattern -> COMPRESS_CONTEXT
  11. Default -> ABORT
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import re

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


class ErrorAction(enum.Enum):
    """What the retry loop should do with this error."""

    RETRY = "retry"
    """Same request, same credential, after backoff."""

    ROTATE_CREDENTIAL = "rotate_credential"
    """Same request, next credential in the pool."""

    FALLBACK_PROVIDER = "fallback_provider"
    """Same request, different provider entirely. (Reserved — treated as ABORT.)"""

    COMPRESS_CONTEXT = "compress_context"
    """Context too large; compress and retry."""

    ABORT = "abort"
    """Fatal; surface to user."""


class ErrorClass(enum.Enum):
    """What kind of error occurred (for logging / metrics)."""

    NETWORK = "network"
    SERVER_5XX = "server_5xx"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CLIENT_4XX = "client_4xx"
    CONTEXT_LENGTH = "context_length"
    STREAM = "stream"
    PARSE = "parse"
    UNKNOWN = "unknown"


@dataclasses.dataclass(frozen=True)
class Classification:
    action: ErrorAction
    error_class: ErrorClass
    reason: str
    """Human-readable explanation for logging."""

    suggested_backoff_s: float | None = None
    """Provider-suggested backoff (e.g., 429 with Retry-After). The retry
    wrapper caps this at ``max_backoff_seconds``."""


# ---------------------------------------------------------------------------
# Provider-specific context-length patterns
# ---------------------------------------------------------------------------


_CONTEXT_LENGTH_PATTERNS = (
    re.compile(r"prompt is too long", re.IGNORECASE),  # Anthropic
    re.compile(r"maximum context length", re.IGNORECASE),  # OpenAI
    re.compile(r"context length .* exceeded", re.IGNORECASE),  # OpenAI variant
    re.compile(r"exceeds the maximum (?:input )?token count", re.IGNORECASE),  # Gemini
    re.compile(r"input length .* exceeds", re.IGNORECASE),  # generic
    re.compile(r"too many tokens", re.IGNORECASE),  # Ollama variant
)


def _matches_context_length(message: str) -> bool:
    return any(p.search(message) for p in _CONTEXT_LENGTH_PATTERNS)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify(
    exc: BaseException,
    *,
    response_status: int | None = None,
    response_text: str | None = None,
    retry_after_header: str | None = None,
) -> Classification:
    """Classify an exception into a recovery action.

    ``response_status`` and ``response_text`` override anything carried
    on the exception itself (useful when the caller already drained
    the body for logging).

    ``retry_after_header`` is the value of the HTTP ``Retry-After``
    header if present; parsed into ``suggested_backoff_s`` when the
    error class is RATE_LIMIT or TIMEOUT.
    """
    message = str(exc) or ""

    # 1. Network-layer errors
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return Classification(
            action=ErrorAction.RETRY,
            error_class=ErrorClass.NETWORK,
            reason=f"Connection error: {message}",
        )
    if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return Classification(
            action=ErrorAction.RETRY,
            error_class=ErrorClass.TIMEOUT,
            reason=f"Timeout: {message}",
        )

    # 2. HTTP status-based classification (must happen BEFORE
    # generic network/stream/parse matching because HTTPStatusError
    # would also match isinstance(httpx.NetworkError) on some httpx
    # versions otherwise).
    status = response_status
    if status is None and isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if response_text is None:
            try:
                response_text = exc.response.text
            except Exception:
                response_text = ""
        if retry_after_header is None:
            retry_after_header = exc.response.headers.get("retry-after")

    if status is not None:
        body = response_text or ""

        if status == 429:
            suggested = _parse_retry_after(retry_after_header)
            return Classification(
                action=ErrorAction.RETRY,
                error_class=ErrorClass.RATE_LIMIT,
                reason="HTTP 429 Too Many Requests",
                suggested_backoff_s=suggested,
            )

        if status == 408:
            suggested = _parse_retry_after(retry_after_header)
            return Classification(
                action=ErrorAction.RETRY,
                error_class=ErrorClass.TIMEOUT,
                reason="HTTP 408 Request Timeout",
                suggested_backoff_s=suggested,
            )

        if 500 <= status < 600:
            if _matches_context_length(body):
                return Classification(
                    action=ErrorAction.COMPRESS_CONTEXT,
                    error_class=ErrorClass.CONTEXT_LENGTH,
                    reason=f"HTTP {status} with context-length message",
                )
            return Classification(
                action=ErrorAction.RETRY,
                error_class=ErrorClass.SERVER_5XX,
                reason=f"HTTP {status} server error",
            )

        if status == 400 and _matches_context_length(body):
            return Classification(
                action=ErrorAction.COMPRESS_CONTEXT,
                error_class=ErrorClass.CONTEXT_LENGTH,
                reason="HTTP 400 with context-length message",
            )

        if 400 <= status < 500:
            return Classification(
                action=ErrorAction.ABORT,
                error_class=ErrorClass.CLIENT_4XX,
                reason=f"HTTP {status} (request malformed or unauthorized)",
            )

    # 3. Mid-stream read errors. ReadError is a subclass of NetworkError;
    # match it BEFORE the generic NetworkError check below so the
    # error_class reads STREAM rather than NETWORK for an interrupted
    # SSE body.
    if isinstance(exc, httpx.ReadError) or "stream" in message.lower():
        return Classification(
            action=ErrorAction.RETRY,
            error_class=ErrorClass.STREAM,
            reason=f"Stream error: {message}",
        )

    # 4. Other httpx network shapes (after status check so a 4xx
    # carried by an HTTPStatusError doesn't get reclassified as network).
    if isinstance(exc, (httpx.RemoteProtocolError, httpx.NetworkError)):
        return Classification(
            action=ErrorAction.RETRY,
            error_class=ErrorClass.NETWORK,
            reason=f"Protocol/network error: {message}",
        )

    # 5. JSON / SSE parse errors during streaming
    if isinstance(exc, ValueError) and "json" in message.lower():
        return Classification(
            action=ErrorAction.RETRY,
            error_class=ErrorClass.PARSE,
            reason=f"Parse error: {message}",
        )

    # 6. Bare exception text matching a context-length pattern
    if _matches_context_length(message):
        return Classification(
            action=ErrorAction.COMPRESS_CONTEXT,
            error_class=ErrorClass.CONTEXT_LENGTH,
            reason=f"Context-length pattern matched in exception: {message}",
        )

    # 7. Default: abort
    return Classification(
        action=ErrorAction.ABORT,
        error_class=ErrorClass.UNKNOWN,
        reason=f"Unclassified error ({type(exc).__name__}): {message}",
    )


def _parse_retry_after(header_value: str | None) -> float | None:
    """Parse an HTTP ``Retry-After`` header value.

    RFC 7231 allows either an integer number of seconds or an
    HTTP-date. Only the integer form is parsed here; date-form
    Retry-After is rare on inference APIs (the rate-limit tracker
    handles wall-clock reset timing separately).
    """
    if not header_value:
        return None
    try:
        return float(header_value.strip())
    except (ValueError, AttributeError):
        return None
