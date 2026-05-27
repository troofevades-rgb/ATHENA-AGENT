"""Sync retry wrapper that consults the error classifier.

The provider surface in this codebase is synchronous
(``stream_chat`` returns ``Iterator[StreamChunk]``), so the wrapper
is synchronous too. The spec's design doc skeleton was written
async-first; this file implements the same contract over plain
``time.sleep`` + sync callbacks. If a future provider goes async,
add an ``async with_retry_async`` next to this; the classifier
itself is shape-agnostic.

Public surface:

  with_retry(operation, *, max_retries, max_backoff_s,
             on_rotate_credential, on_compress_context,
             provider_label) -> T
  RetryBudgetExceeded
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

import httpx

from .error_classifier import Classification, ErrorAction, ErrorClass, classify

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryBudgetExceeded(Exception):
    """Too many retries within a single operation."""

    def __init__(self, attempts: int, last_classification: Classification) -> None:
        super().__init__(
            f"Retry budget exceeded after {attempts} attempts: {last_classification.reason}"
        )
        self.attempts = attempts
        self.last_classification = last_classification


def with_retry(
    operation: Callable[[], T],
    *,
    max_retries: int = 5,
    max_backoff_s: float = 30.0,
    on_rotate_credential: Callable[[], bool] | None = None,
    on_compress_context: Callable[[], bool] | None = None,
    on_retry: Callable[[Classification], None] | None = None,
    on_abort: Callable[[Classification], None] | None = None,
    provider_label: str = "<unknown>",
) -> T:
    """Run ``operation()`` with classifier-driven retries.

    On each failure, the classifier inspects the exception and decides
    the recovery action:

    - ``RETRY`` -> sleep with exponential backoff (or the classifier's
      suggested_backoff_s if present), then re-call ``operation``.
    - ``ROTATE_CREDENTIAL`` -> call ``on_rotate_credential()``; if it
      returns True, re-call ``operation``. If False (or no callback),
      escalate by re-raising.
    - ``COMPRESS_CONTEXT`` -> call ``on_compress_context()``; same
      escalation rule as rotate.
    - ``FALLBACK_PROVIDER`` -> reserved; treated as abort.
    - ``ABORT`` -> re-raise.

    Caps:

    - At most ``max_retries`` recovery attempts. After that, raise
      ``RetryBudgetExceeded``.
    - Backoff capped at ``max_backoff_s``.

    BaseException subclasses NOT derived from ``Exception``
    (``KeyboardInterrupt``, ``SystemExit``) propagate immediately
    without classification. ``asyncio.CancelledError`` is an
    ``Exception`` since 3.8 — the classifier puts it in UNKNOWN, which
    aborts, so it also propagates without retry.
    """
    attempt = 0
    last_classification: Classification | None = None
    # Track consecutive 429s. The classifier returns RETRY for the
    # first 429 (single-key users benefit from backoff alone). After
    # 2 in a row on the same credential, escalate to
    # ROTATE_CREDENTIAL so multi-key users actually switch keys
    # instead of grinding on a rate-limited one.
    consecutive_429s = 0
    _ROTATE_AFTER_N_429s = 2

    while True:
        try:
            return operation()
        except (KeyboardInterrupt, SystemExit):
            # User-driven interrupts and process exit are never
            # retried; let them bubble straight to the caller.
            raise
        except Exception as exc:
            classification = _classify_from_exc(exc)
            last_classification = classification
            attempt += 1

            # Escalate consecutive 429s to ROTATE_CREDENTIAL so the
            # rotate callback gets a chance to swap creds.
            if classification.error_class is ErrorClass.RATE_LIMIT:
                consecutive_429s += 1
                if (
                    consecutive_429s >= _ROTATE_AFTER_N_429s
                    and on_rotate_credential is not None
                ):
                    classification = Classification(
                        action=ErrorAction.ROTATE_CREDENTIAL,
                        error_class=classification.error_class,
                        reason=(
                            f"{consecutive_429s} consecutive 429s — "
                            f"escalating to credential rotation"
                        ),
                        suggested_backoff_s=classification.suggested_backoff_s,
                    )
            else:
                consecutive_429s = 0

            if attempt > max_retries:
                logger.error(
                    "[%s] retry budget exceeded (attempt=%d, class=%s, reason=%s)",
                    provider_label,
                    attempt,
                    classification.error_class.value,
                    classification.reason,
                )
                if on_abort is not None:
                    on_abort(classification)
                raise RetryBudgetExceeded(attempt, classification) from exc

            action = classification.action

            if action is ErrorAction.ABORT:
                logger.error(
                    "[%s] aborting: %s (class=%s)",
                    provider_label,
                    classification.reason,
                    classification.error_class.value,
                )
                if on_abort is not None:
                    on_abort(classification)
                raise

            if action is ErrorAction.FALLBACK_PROVIDER:
                # Reserved; treat as abort until cross-provider
                # fallback machinery exists (Tier 3/4).
                logger.error("[%s] fallback_provider not implemented; aborting", provider_label)
                if on_abort is not None:
                    on_abort(classification)
                raise

            # Anything past here is a retry of some kind; fire the counter hook.
            if on_retry is not None:
                on_retry(classification)

            if action is ErrorAction.ROTATE_CREDENTIAL:
                if on_rotate_credential is None or not on_rotate_credential():
                    logger.error(
                        "[%s] cannot rotate credential; aborting",
                        provider_label,
                    )
                    raise
                logger.info(
                    "[%s] rotated credential (attempt %d/%d)",
                    provider_label,
                    attempt,
                    max_retries,
                )
                # Reset the 429 counter so the freshly-rotated credential
                # gets its own 2-strike budget. Without this, the new
                # credential would inherit consecutive_429s=2 and any
                # single 429 on it would immediately re-rotate — burning
                # through the entire pool on what might be a transient
                # spike.
                consecutive_429s = 0
                continue

            if action is ErrorAction.COMPRESS_CONTEXT:
                if on_compress_context is None or not on_compress_context():
                    logger.error(
                        "[%s] cannot compress context; aborting",
                        provider_label,
                    )
                    raise
                logger.info(
                    "[%s] compressed context (attempt %d/%d)",
                    provider_label,
                    attempt,
                    max_retries,
                )
                continue

            # ErrorAction.RETRY: backoff + sleep.
            backoff = classification.suggested_backoff_s
            if backoff is None:
                backoff = _backoff_seconds(attempt=attempt, max_backoff_s=max_backoff_s)
            else:
                backoff = min(backoff, max_backoff_s)
            logger.info(
                "[%s] retry attempt %d/%d after %.1fs (class=%s, reason=%s)",
                provider_label,
                attempt,
                max_retries,
                backoff,
                classification.error_class.value,
                classification.reason,
            )
            if backoff > 0:
                time.sleep(backoff)


def _backoff_seconds(*, attempt: int, max_backoff_s: float) -> float:
    """Exponential backoff with jitter, capped at ``max_backoff_s``.

    attempt=1 -> ~2s + jitter, attempt=2 -> ~4s + jitter,
    attempt=3 -> ~8s + jitter, etc.
    """
    base = min(2.0**attempt, max_backoff_s)
    jitter = random.uniform(0.0, 1.0)
    return min(base + jitter, max_backoff_s)


def _classify_from_exc(exc: BaseException) -> Classification:
    """Pull HTTP status / body / Retry-After off the exception if
    present and dispatch into the classifier."""
    response_status: int | None = None
    response_text: str | None = None
    retry_after: str | None = None
    if isinstance(exc, httpx.HTTPStatusError):
        response_status = exc.response.status_code
        try:
            response_text = exc.response.text
        except Exception:
            response_text = ""
        retry_after = exc.response.headers.get("retry-after")
    return classify(
        exc,
        response_status=response_status,
        response_text=response_text,
        retry_after_header=retry_after,
    )
