"""Rate-limit tracking for inference API responses.

Captures the standard ``x-ratelimit-*`` header schema and (optionally)
the ``anthropic-ratelimit-*`` schema. Surfaces remaining capacity and
reset timing so the agent can preemptively throttle instead of
hitting 429s.

Pure data + parsing. No I/O.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)


# Standard 12-header schema. Generic OpenAI-compatible / Nous / OpenRouter.
_GENERIC_HEADERS = {
    "limit_requests_min": "x-ratelimit-limit-requests",
    "limit_requests_hr": "x-ratelimit-limit-requests-1h",
    "limit_tokens_min": "x-ratelimit-limit-tokens",
    "limit_tokens_hr": "x-ratelimit-limit-tokens-1h",
    "remaining_requests_min": "x-ratelimit-remaining-requests",
    "remaining_requests_hr": "x-ratelimit-remaining-requests-1h",
    "remaining_tokens_min": "x-ratelimit-remaining-tokens",
    "remaining_tokens_hr": "x-ratelimit-remaining-tokens-1h",
    "reset_requests_min": "x-ratelimit-reset-requests",
    "reset_requests_hr": "x-ratelimit-reset-requests-1h",
    "reset_tokens_min": "x-ratelimit-reset-tokens",
    "reset_tokens_hr": "x-ratelimit-reset-tokens-1h",
}

# Anthropic uses anthropic-ratelimit-* prefix. Different fields.
_ANTHROPIC_HEADERS = {
    "limit_requests_min": "anthropic-ratelimit-requests-limit",
    "remaining_requests_min": "anthropic-ratelimit-requests-remaining",
    "reset_requests_min": "anthropic-ratelimit-requests-reset",
    "limit_tokens_min": "anthropic-ratelimit-tokens-limit",
    "remaining_tokens_min": "anthropic-ratelimit-tokens-remaining",
    "reset_tokens_min": "anthropic-ratelimit-tokens-reset",
    "limit_input_tokens_min": "anthropic-ratelimit-input-tokens-limit",
    "remaining_input_tokens_min": "anthropic-ratelimit-input-tokens-remaining",
    "limit_output_tokens_min": "anthropic-ratelimit-output-tokens-limit",
    "remaining_output_tokens_min": "anthropic-ratelimit-output-tokens-remaining",
}


@dataclasses.dataclass(frozen=True)
class RateLimitTracker:
    """Parsed rate-limit state from a single response.

    Times are stored as ABSOLUTE Unix seconds (already converted from
    the relative "seconds until reset" values in the headers). This
    way the state is meaningful across server clock drift and can be
    compared to ``time.time()`` directly.
    """

    provider: str
    captured_at: float  # time.time() when the response landed

    limit_requests_min: int | None = None
    limit_requests_hr: int | None = None
    limit_tokens_min: int | None = None
    limit_tokens_hr: int | None = None

    remaining_requests_min: int | None = None
    remaining_requests_hr: int | None = None
    remaining_tokens_min: int | None = None
    remaining_tokens_hr: int | None = None

    reset_requests_min_at: float | None = None  # absolute Unix seconds
    reset_requests_hr_at: float | None = None
    reset_tokens_min_at: float | None = None
    reset_tokens_hr_at: float | None = None

    # ---------------------------------------------------------------
    # Parsing
    # ---------------------------------------------------------------

    @classmethod
    def from_headers(
        cls,
        headers: Mapping[str, str],
        *,
        provider: str,
        schema: str = "generic",
    ) -> RateLimitTracker | None:
        """Parse rate-limit state from response headers.

        ``schema``:
            ``"generic"`` — OpenAI-compat / Nous / OpenRouter standard
            ``"anthropic"`` — Anthropic's ``anthropic-ratelimit-*`` schema

        Returns ``None`` if no rate-limit headers are present.
        """
        now = time.time()
        if schema == "anthropic":
            return cls._parse_anthropic(headers, provider=provider, now=now)
        return cls._parse_generic(headers, provider=provider, now=now)

    @classmethod
    def _parse_generic(
        cls,
        headers: Mapping[str, str],
        *,
        provider: str,
        now: float,
    ) -> RateLimitTracker | None:
        fields: dict[str, Any] = {"provider": provider, "captured_at": now}
        found_any = False

        for field_name, header_name in _GENERIC_HEADERS.items():
            value = _header(headers, header_name)
            if value is None:
                continue
            found_any = True

            if field_name.startswith(("limit_", "remaining_")):
                parsed = _parse_int(value)
                if parsed is not None:
                    fields[field_name] = parsed
            elif field_name.startswith("reset_"):
                seconds_until = _parse_float(value)
                if seconds_until is not None:
                    fields[field_name + "_at"] = now + seconds_until

        if not found_any:
            return None
        return cls(**fields)

    @classmethod
    def _parse_anthropic(
        cls,
        headers: Mapping[str, str],
        *,
        provider: str,
        now: float,
    ) -> RateLimitTracker | None:
        fields: dict[str, Any] = {"provider": provider, "captured_at": now}
        found_any = False

        for field_name, header_name in _ANTHROPIC_HEADERS.items():
            value = _header(headers, header_name)
            if value is None:
                continue
            found_any = True

            # Anthropic reports input- and output-specific token limits
            # that we don't model separately yet; the combined
            # tokens-limit/tokens-remaining values are what we track.
            if "input_tokens" in field_name or "output_tokens" in field_name:
                continue

            if field_name.startswith(("limit_", "remaining_")):
                parsed = _parse_int(value)
                if parsed is not None:
                    fields[field_name] = parsed
            elif field_name.startswith("reset_"):
                # Anthropic returns an ISO 8601 timestamp; convert to Unix.
                ts = _parse_iso_to_unix(value)
                if ts is not None:
                    fields[field_name + "_at"] = ts

        if not found_any:
            return None
        return cls(**fields)

    # ---------------------------------------------------------------
    # Throttle decision
    # ---------------------------------------------------------------

    def usage_ratio_requests_min(self) -> float | None:
        if self.limit_requests_min and self.remaining_requests_min is not None:
            return 1.0 - (self.remaining_requests_min / self.limit_requests_min)
        return None

    def usage_ratio_tokens_min(self) -> float | None:
        if self.limit_tokens_min and self.remaining_tokens_min is not None:
            return 1.0 - (self.remaining_tokens_min / self.limit_tokens_min)
        return None

    def should_throttle(self, threshold: float = 0.95) -> bool:
        """Return True if we're at or above ``threshold`` of either rate limit.

        Default 0.95 = throttle when remaining < 5%.
        """
        for ratio in (
            self.usage_ratio_requests_min(),
            self.usage_ratio_tokens_min(),
        ):
            if ratio is not None and ratio >= threshold:
                return True
        return False

    def throttle_seconds(self, threshold: float = 0.95) -> float:
        """How long to wait before the next request to stay under the limit.

        Returns the time until the soonest reset, capped at 60s.
        Returns 0 if we don't have enough info or we shouldn't throttle.
        """
        if not self.should_throttle(threshold=threshold):
            return 0.0
        now = time.time()
        candidates = [
            self.reset_requests_min_at,
            self.reset_tokens_min_at,
        ]
        soonest = min((r for r in candidates if r is not None), default=None)
        if soonest is None:
            return 0.0
        return max(0.0, min(60.0, soonest - now))

    # ---------------------------------------------------------------
    # Display
    # ---------------------------------------------------------------

    def format(self) -> str:
        """One-line human-readable summary for ``/status``."""
        parts: list[str] = []
        now = time.time()

        if self.remaining_requests_min is not None and self.limit_requests_min:
            reset_str = (
                f"reset in {int(self.reset_requests_min_at - now)}s"
                if self.reset_requests_min_at
                else "no reset info"
            )
            parts.append(
                f"RPM: {self.remaining_requests_min}/{self.limit_requests_min} ({reset_str})"
            )

        if self.remaining_tokens_min is not None and self.limit_tokens_min:
            reset_str = (
                f"reset in {int(self.reset_tokens_min_at - now)}s"
                if self.reset_tokens_min_at
                else "no reset info"
            )
            parts.append(
                f"TPM: {self.remaining_tokens_min:,}/{self.limit_tokens_min:,} ({reset_str})"
            )

        if self.remaining_requests_hr is not None and self.limit_requests_hr:
            parts.append(f"RPH: {self.remaining_requests_hr:,}/{self.limit_requests_hr:,}")

        return "  ".join(parts) if parts else "no rate-limit info"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup."""
    if name in headers:
        return headers[name]
    name_lower = name.lower()
    for key, value in headers.items():
        if key.lower() == name_lower:
            return value
    return None


def _parse_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return None


def _parse_float(value: str) -> float | None:
    try:
        # Some providers return "30s" or "30" — strip a trailing "s".
        return float(value.strip().rstrip("s"))
    except (ValueError, AttributeError):
        return None


def _parse_iso_to_unix(value: str) -> float | None:
    """Parse Anthropic's ISO 8601 reset timestamp to Unix seconds."""
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        return None
