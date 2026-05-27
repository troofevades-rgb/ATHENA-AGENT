"""Tests for athena.providers.retry_utils (T2-03.4).

The wrapper is sync (matches athena's sync provider surface). Spec's
async test skeleton is adapted to plain ``def`` tests against the
sync API.
"""

from __future__ import annotations

import httpx
import pytest

from athena.providers.retry_utils import RetryBudgetExceeded, with_retry


def _http_status_error(
    status: int, headers: dict | None = None, text: str = ""
) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.test/x")
    response = httpx.Response(status_code=status, text=text, headers=headers or {})
    return httpx.HTTPStatusError("err", request=request, response=response)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_succeeds_on_first_try() -> None:
    def op() -> str:
        return "ok"

    assert with_retry(op) == "ok"


# ---------------------------------------------------------------------------
# RETRY action
# ---------------------------------------------------------------------------


def test_retries_on_5xx_then_succeeds() -> None:
    attempts = 0

    def op() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _http_status_error(503, text="oops")
        return "ok"

    result = with_retry(op, max_backoff_s=0.01)
    assert result == "ok"
    assert attempts == 3


def test_retries_on_connect_error_then_succeeds() -> None:
    attempts = 0

    def op() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise httpx.ConnectError("refused")
        return "ok"

    assert with_retry(op, max_backoff_s=0.01) == "ok"
    assert attempts == 2


def test_retry_after_header_caps_at_max_backoff(monkeypatch) -> None:
    """A server-supplied Retry-After of 600s is clamped to
    max_backoff_s (so we don't accidentally sleep for ten minutes)."""
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "athena.providers.retry_utils.time.sleep",
        lambda s: sleep_calls.append(s),
    )

    attempts = 0

    def op() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise _http_status_error(429, headers={"retry-after": "600"})
        return "ok"

    with_retry(op, max_backoff_s=2.0)
    assert sleep_calls
    assert sleep_calls[0] == 2.0


# ---------------------------------------------------------------------------
# ABORT action
# ---------------------------------------------------------------------------


def test_aborts_on_4xx() -> None:
    def op() -> str:
        raise _http_status_error(401, text="unauthorized")

    with pytest.raises(httpx.HTTPStatusError):
        with_retry(op)


def test_aborts_on_unknown_exception() -> None:
    def op() -> str:
        raise RuntimeError("opaque")

    with pytest.raises(RuntimeError):
        with_retry(op)


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def test_exceeds_retry_budget_raises_RetryBudgetExceeded() -> None:
    def op() -> str:
        raise httpx.ConnectError("nope")

    with pytest.raises(RetryBudgetExceeded) as excinfo:
        with_retry(op, max_retries=2, max_backoff_s=0.01)
    assert excinfo.value.attempts == 3
    assert excinfo.value.last_classification.error_class.value == "network"


# ---------------------------------------------------------------------------
# Callback paths
# ---------------------------------------------------------------------------


def test_rotate_credential_callback_invoked_on_repeated_429() -> None:
    """After 2 consecutive 429s, with_retry escalates to ROTATE_CREDENTIAL
    and invokes on_rotate_credential. If the callback returns False
    (no more credentials available), the original HTTPStatusError
    re-raises — the caller sees a clean rate-limit error instead of
    an indefinite retry loop.

    First 429 → RETRY (single-key users benefit from backoff). Second
    consecutive 429 → ROTATE_CREDENTIAL (multi-key users actually
    switch keys instead of grinding on a rate-limited one)."""

    def op() -> str:
        raise _http_status_error(429, headers={"retry-after": "0"})

    rotate_calls = 0

    def on_rotate() -> bool:
        nonlocal rotate_calls
        rotate_calls += 1
        return False

    with pytest.raises(httpx.HTTPStatusError):
        with_retry(
            op,
            on_rotate_credential=on_rotate,
            max_backoff_s=0.01,
            max_retries=5,
        )
    assert rotate_calls == 1, (
        f"expected rotate callback to fire exactly once after the "
        f"second consecutive 429; fired {rotate_calls} times"
    )


def test_rotate_success_resets_consecutive_429_counter() -> None:
    """After a successful rotation, the new credential should get its
    own 2-strike budget — not inherit ``consecutive_429s=2`` from the
    rotated-out key. Otherwise any single 429 on the new key triggers
    immediate re-rotation, burning through the entire pool on what
    might be a transient spike.

    Regression test for retry_utils.py — the counter must reset on
    rotation success."""
    call_count = 0

    def op() -> str:
        nonlocal call_count
        call_count += 1
        # First 3 calls return 429 (forces 2 rotations); 4th succeeds.
        # With the bug, the second rotation fires on the 3rd 429
        # (because counter was already at 2 after rotating once).
        # With the fix, the second rotation only fires after TWO
        # more 429s post-rotation.
        if call_count <= 3:
            raise _http_status_error(429, headers={"retry-after": "0"})
        return "ok"

    rotate_calls = 0

    def on_rotate() -> bool:
        nonlocal rotate_calls
        rotate_calls += 1
        return True

    result = with_retry(
        op,
        on_rotate_credential=on_rotate,
        max_backoff_s=0.01,
        max_retries=10,
    )
    assert result == "ok"
    # 3 × 429 in a row would have rotated AT MOST 2 times if the
    # counter resets properly (after 2 consecutive 429s, after another
    # 2 if we hadn't succeeded). With the bug it would rotate 2 times
    # too in this scenario, so let's verify the specific cadence:
    # call 1: 429, counter=1 → RETRY
    # call 2: 429, counter=2 → ROTATE (counter resets to 0)
    # call 3: 429, counter=1 → RETRY
    # call 4: ok
    # Expected rotations: 1.
    # Without the reset, call 3 would have counter=3 → ROTATE again.
    assert rotate_calls == 1, (
        f"expected exactly 1 rotation; got {rotate_calls}. The "
        f"consecutive_429s counter is not resetting on rotation "
        f"success — the new credential is starting at count=2 and "
        f"any single 429 immediately re-rotates."
    )


def test_rotate_callback_success_continues_retrying() -> None:
    """When on_rotate returns True (swap succeeded), with_retry
    continues with the next attempt. The consecutive_429s counter
    resets on a non-429 outcome — so a rotation that fixes the
    problem allows the operation to ultimately succeed."""
    call_count = 0

    def op() -> str:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise _http_status_error(429, headers={"retry-after": "0"})
        return "ok after rotation"

    rotated = []

    def on_rotate() -> bool:
        rotated.append(True)
        return True

    result = with_retry(
        op,
        on_rotate_credential=on_rotate,
        max_backoff_s=0.01,
        max_retries=5,
    )
    assert result == "ok after rotation"
    assert len(rotated) == 1, (
        f"expected exactly one rotation; got {len(rotated)}"
    )


def test_compress_context_callback_invoked() -> None:
    """When the classifier says COMPRESS_CONTEXT, with_retry calls
    on_compress_context. If it returns True, the next attempt runs.
    If True repeatedly, the wrapper eventually re-raises after
    max_retries."""
    op_calls = 0

    def op() -> str:
        nonlocal op_calls
        op_calls += 1
        raise Exception("prompt is too long")

    compress_calls = 0

    def on_compress() -> bool:
        nonlocal compress_calls
        compress_calls += 1
        return True

    with pytest.raises(Exception):
        with_retry(
            op,
            on_compress_context=on_compress,
            max_retries=2,
            max_backoff_s=0.01,
        )

    # The wrapper called on_compress at least once before giving up.
    assert compress_calls >= 1
    # And the operation ran multiple times: initial + at least one
    # post-compression retry.
    assert op_calls >= 2


def test_compress_context_callback_returning_false_aborts() -> None:
    """If on_compress_context returns False (compression not possible),
    the wrapper escalates to ABORT immediately."""

    def op() -> str:
        raise Exception("prompt is too long")

    def on_compress() -> bool:
        return False

    with pytest.raises(Exception, match="prompt is too long"):
        with_retry(op, on_compress_context=on_compress, max_retries=5)


# ---------------------------------------------------------------------------
# Interrupt propagation
# ---------------------------------------------------------------------------


def test_keyboard_interrupt_not_retried() -> None:
    """KeyboardInterrupt propagates immediately; never classified."""
    op_calls = 0

    def op() -> str:
        nonlocal op_calls
        op_calls += 1
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        with_retry(op, max_retries=5)
    assert op_calls == 1  # exactly one call; no retry


def test_cancelled_error_not_retried() -> None:
    """asyncio.CancelledError is an Exception (3.8+); it falls
    through as UNKNOWN -> ABORT, which re-raises immediately."""
    import asyncio

    op_calls = 0

    def op() -> str:
        nonlocal op_calls
        op_calls += 1
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        with_retry(op, max_retries=5)
    assert op_calls == 1


def test_system_exit_not_retried() -> None:
    op_calls = 0

    def op() -> str:
        nonlocal op_calls
        op_calls += 1
        raise SystemExit(2)

    with pytest.raises(SystemExit):
        with_retry(op, max_retries=5)
    assert op_calls == 1
