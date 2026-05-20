"""Tests for athena.providers.error_classifier (T2-03.2)."""

from __future__ import annotations

import httpx
import pytest

from athena.providers.error_classifier import (
    ErrorAction,
    ErrorClass,
    classify,
)


def _http_status_error(
    status: int, text: str = "", headers: dict | None = None
) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.test/x")
    response = httpx.Response(status_code=status, text=text, headers=headers or {})
    return httpx.HTTPStatusError("...", request=request, response=response)


# ---------------------------------------------------------------------------
# Network-layer errors
# ---------------------------------------------------------------------------


def test_connect_error_retries() -> None:
    c = classify(httpx.ConnectError("connection refused"))
    assert c.action is ErrorAction.RETRY
    assert c.error_class is ErrorClass.NETWORK


def test_connect_timeout_retries() -> None:
    c = classify(httpx.ConnectTimeout("connect timed out"))
    assert c.action is ErrorAction.RETRY
    assert c.error_class is ErrorClass.NETWORK


def test_read_timeout_retries() -> None:
    c = classify(httpx.ReadTimeout("timed out"))
    assert c.action is ErrorAction.RETRY
    assert c.error_class is ErrorClass.TIMEOUT


# ---------------------------------------------------------------------------
# HTTP 5xx
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_retries(status: int) -> None:
    c = classify(_http_status_error(status, "server oops"))
    assert c.action is ErrorAction.RETRY
    assert c.error_class is ErrorClass.SERVER_5XX


def test_5xx_with_context_length_compresses() -> None:
    """A 5xx whose body still hints at context length compresses rather
    than retrying blindly."""
    c = classify(_http_status_error(503, "prompt is too long for this model"))
    assert c.action is ErrorAction.COMPRESS_CONTEXT
    assert c.error_class is ErrorClass.CONTEXT_LENGTH


# ---------------------------------------------------------------------------
# HTTP 429 (rate limit)
# ---------------------------------------------------------------------------


def test_429_retries_with_retry_after_header() -> None:
    c = classify(
        _http_status_error(429, "rate limit", headers={"retry-after": "30"}),
    )
    assert c.action is ErrorAction.RETRY
    assert c.error_class is ErrorClass.RATE_LIMIT
    assert c.suggested_backoff_s == 30.0


def test_429_without_retry_after() -> None:
    c = classify(_http_status_error(429, "rate limit"))
    assert c.action is ErrorAction.RETRY
    assert c.error_class is ErrorClass.RATE_LIMIT
    assert c.suggested_backoff_s is None


# ---------------------------------------------------------------------------
# HTTP 408
# ---------------------------------------------------------------------------


def test_408_retries() -> None:
    c = classify(_http_status_error(408, "request timeout"))
    assert c.action is ErrorAction.RETRY
    assert c.error_class is ErrorClass.TIMEOUT


# ---------------------------------------------------------------------------
# HTTP 4xx other
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_4xx_aborts(status: int) -> None:
    c = classify(_http_status_error(status, "bad request"))
    assert c.action is ErrorAction.ABORT
    assert c.error_class is ErrorClass.CLIENT_4XX


# ---------------------------------------------------------------------------
# Context-length errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "msg",
    [
        "prompt is too long",
        "This model's maximum context length is 200000 tokens.",
        "Input length 8192 exceeds the maximum input token count for this model",
        "context length 16385 exceeded; reduce your input",
        "too many tokens for current context window",
    ],
)
def test_context_length_compresses_on_400(msg: str) -> None:
    c = classify(_http_status_error(400, msg))
    assert c.action is ErrorAction.COMPRESS_CONTEXT
    assert c.error_class is ErrorClass.CONTEXT_LENGTH


def test_context_length_in_bare_exception_text() -> None:
    """Some providers raise context-length as a bare RuntimeError before
    an HTTP status is available."""
    c = classify(RuntimeError("prompt is too long for context"))
    assert c.action is ErrorAction.COMPRESS_CONTEXT
    assert c.error_class is ErrorClass.CONTEXT_LENGTH


# ---------------------------------------------------------------------------
# Stream and parse errors
# ---------------------------------------------------------------------------


def test_read_error_retries_as_stream() -> None:
    c = classify(httpx.ReadError("connection reset mid-stream"))
    assert c.action is ErrorAction.RETRY
    assert c.error_class is ErrorClass.STREAM


def test_stream_keyword_in_message_retries() -> None:
    c = classify(RuntimeError("stream ended unexpectedly"))
    assert c.action is ErrorAction.RETRY
    assert c.error_class is ErrorClass.STREAM


def test_json_parse_error_retries() -> None:
    c = classify(ValueError("invalid json: unexpected EOF"))
    assert c.action is ErrorAction.RETRY
    assert c.error_class is ErrorClass.PARSE


# ---------------------------------------------------------------------------
# Default
# ---------------------------------------------------------------------------


def test_unknown_aborts() -> None:
    c = classify(Exception("something else entirely"))
    assert c.action is ErrorAction.ABORT
    assert c.error_class is ErrorClass.UNKNOWN


def test_value_error_without_json_aborts() -> None:
    """A ValueError whose message has no 'json' substring falls through
    to the unknown bucket."""
    c = classify(ValueError("invalid argument"))
    assert c.action is ErrorAction.ABORT
    assert c.error_class is ErrorClass.UNKNOWN


# ---------------------------------------------------------------------------
# Overrides via keyword args
# ---------------------------------------------------------------------------


def test_response_status_override_wins_over_exception() -> None:
    """If the caller passes response_status, we trust it rather than
    digging into the exception."""
    c = classify(Exception("opaque"), response_status=503, response_text="server error")
    assert c.action is ErrorAction.RETRY
    assert c.error_class is ErrorClass.SERVER_5XX
