"""Tests for athena.providers.rate_limit_tracker (T2-02.2)."""

from __future__ import annotations

import time

from athena.providers.rate_limit_tracker import RateLimitTracker

# ---------------------------------------------------------------------------
# Generic schema parsing
# ---------------------------------------------------------------------------


def test_parse_generic_full_schema() -> None:
    headers = {
        "x-ratelimit-limit-requests": "50",
        "x-ratelimit-limit-requests-1h": "3000",
        "x-ratelimit-limit-tokens": "30000",
        "x-ratelimit-limit-tokens-1h": "1000000",
        "x-ratelimit-remaining-requests": "47",
        "x-ratelimit-remaining-requests-1h": "2841",
        "x-ratelimit-remaining-tokens": "28440",
        "x-ratelimit-remaining-tokens-1h": "892000",
        "x-ratelimit-reset-requests": "12",
        "x-ratelimit-reset-requests-1h": "2820",
        "x-ratelimit-reset-tokens": "12",
        "x-ratelimit-reset-tokens-1h": "2820",
    }
    tracker = RateLimitTracker.from_headers(headers, provider="test")
    assert tracker is not None
    assert tracker.limit_requests_min == 50
    assert tracker.remaining_requests_min == 47
    assert tracker.limit_tokens_min == 30000
    assert tracker.remaining_tokens_min == 28440
    assert tracker.reset_requests_min_at is not None
    assert abs(tracker.reset_requests_min_at - (time.time() + 12)) < 2


def test_parse_no_headers_returns_none() -> None:
    assert RateLimitTracker.from_headers({}, provider="test") is None


def test_parse_partial_headers() -> None:
    """Only request count, no token info — still useful."""
    headers = {
        "x-ratelimit-limit-requests": "50",
        "x-ratelimit-remaining-requests": "47",
        "x-ratelimit-reset-requests": "12",
    }
    tracker = RateLimitTracker.from_headers(headers, provider="test")
    assert tracker is not None
    assert tracker.limit_requests_min == 50
    assert tracker.limit_tokens_min is None


def test_case_insensitive_headers() -> None:
    headers = {
        "X-RateLimit-Limit-Requests": "50",
        "X-RateLimit-Remaining-Requests": "47",
    }
    tracker = RateLimitTracker.from_headers(headers, provider="test")
    assert tracker is not None
    assert tracker.limit_requests_min == 50


def test_malformed_header_value_skipped() -> None:
    headers = {
        "x-ratelimit-limit-requests": "fifty",  # not a number
        "x-ratelimit-remaining-requests": "47",
    }
    tracker = RateLimitTracker.from_headers(headers, provider="test")
    assert tracker is not None
    assert tracker.limit_requests_min is None  # parse failed silently
    assert tracker.remaining_requests_min == 47


def test_seconds_with_trailing_s_suffix() -> None:
    """Some providers report reset as '30s' rather than '30'."""
    headers = {
        "x-ratelimit-limit-requests": "100",
        "x-ratelimit-remaining-requests": "50",
        "x-ratelimit-reset-requests": "30s",
    }
    tracker = RateLimitTracker.from_headers(headers, provider="test")
    assert tracker is not None
    assert tracker.reset_requests_min_at is not None
    assert abs(tracker.reset_requests_min_at - (time.time() + 30)) < 2


# ---------------------------------------------------------------------------
# Anthropic schema parsing
# ---------------------------------------------------------------------------


def test_parse_anthropic_schema() -> None:
    headers = {
        "anthropic-ratelimit-requests-limit": "50",
        "anthropic-ratelimit-requests-remaining": "47",
        "anthropic-ratelimit-requests-reset": "2099-05-19T14:51:53Z",
        "anthropic-ratelimit-tokens-limit": "30000",
        "anthropic-ratelimit-tokens-remaining": "28440",
        # Input-/output- token-specific fields are silently dropped:
        "anthropic-ratelimit-input-tokens-limit": "20000",
        "anthropic-ratelimit-input-tokens-remaining": "19000",
    }
    tracker = RateLimitTracker.from_headers(headers, provider="anthropic", schema="anthropic")
    assert tracker is not None
    assert tracker.limit_requests_min == 50
    assert tracker.remaining_requests_min == 47
    assert tracker.limit_tokens_min == 30000
    assert tracker.remaining_tokens_min == 28440
    assert tracker.reset_requests_min_at is not None
    # The 2099 timestamp lands far in the future.
    assert tracker.reset_requests_min_at > time.time()


# ---------------------------------------------------------------------------
# Throttle logic
# ---------------------------------------------------------------------------


def test_should_throttle_when_above_threshold() -> None:
    headers = {
        "x-ratelimit-limit-requests": "100",
        "x-ratelimit-remaining-requests": "4",  # 96% used, above 95% default
        "x-ratelimit-reset-requests": "30",
    }
    tracker = RateLimitTracker.from_headers(headers, provider="test")
    assert tracker is not None
    assert tracker.should_throttle() is True


def test_should_not_throttle_when_below_threshold() -> None:
    headers = {
        "x-ratelimit-limit-requests": "100",
        "x-ratelimit-remaining-requests": "50",  # 50% used
        "x-ratelimit-reset-requests": "30",
    }
    tracker = RateLimitTracker.from_headers(headers, provider="test")
    assert tracker is not None
    assert tracker.should_throttle() is False


def test_throttle_seconds_returns_time_until_reset() -> None:
    headers = {
        "x-ratelimit-limit-requests": "100",
        "x-ratelimit-remaining-requests": "4",
        "x-ratelimit-reset-requests": "30",
    }
    tracker = RateLimitTracker.from_headers(headers, provider="test")
    assert tracker is not None
    sec = tracker.throttle_seconds()
    assert 25 < sec <= 30  # roughly 30, allowing for small clock drift


def test_throttle_seconds_capped_at_60() -> None:
    headers = {
        "x-ratelimit-limit-requests": "100",
        "x-ratelimit-remaining-requests": "4",
        "x-ratelimit-reset-requests": "120",
    }
    tracker = RateLimitTracker.from_headers(headers, provider="test")
    assert tracker is not None
    assert tracker.throttle_seconds() == 60.0


def test_throttle_seconds_zero_when_not_throttling() -> None:
    headers = {
        "x-ratelimit-limit-requests": "100",
        "x-ratelimit-remaining-requests": "50",
        "x-ratelimit-reset-requests": "30",
    }
    tracker = RateLimitTracker.from_headers(headers, provider="test")
    assert tracker is not None
    assert tracker.throttle_seconds() == 0.0


def test_throttle_threshold_argument_overrides_default() -> None:
    """Passing threshold=0.4 throttles at 40% usage."""
    headers = {
        "x-ratelimit-limit-requests": "100",
        "x-ratelimit-remaining-requests": "50",  # 50% used
        "x-ratelimit-reset-requests": "30",
    }
    tracker = RateLimitTracker.from_headers(headers, provider="test")
    assert tracker is not None
    assert tracker.should_throttle(threshold=0.4) is True
    assert tracker.should_throttle(threshold=0.6) is False


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def test_format_with_full_info() -> None:
    headers = {
        "x-ratelimit-limit-requests": "50",
        "x-ratelimit-remaining-requests": "47",
        "x-ratelimit-reset-requests": "12",
        "x-ratelimit-limit-tokens": "30000",
        "x-ratelimit-remaining-tokens": "28440",
        "x-ratelimit-reset-tokens": "12",
    }
    tracker = RateLimitTracker.from_headers(headers, provider="test")
    assert tracker is not None
    formatted = tracker.format()
    assert "RPM: 47/50" in formatted
    assert "TPM: 28,440/30,000" in formatted


def test_format_with_no_info() -> None:
    """Tracker present but all fields None (constructed directly, not via from_headers)."""
    tracker = RateLimitTracker(provider="test", captured_at=time.time())
    assert tracker.format() == "no rate-limit info"
