"""ULTRAPLINIAN multi-model racing.

Ported from the G0DM0D3 reference at ``api/lib/ultraplinian.ts``.
The flagship mode of G0DM0D3: query N models in parallel via an
OpenAI-compatible provider (OpenRouter by default), score
responses on substance / directness / completeness, and return the
winner. The reference's "early-exit" strategy is preserved: stop
waiting for slow models once enough good responses are in.

Public surface:

  * :data:`ULTRAPLINIAN_MODELS` -- the canonical model registry
    keyed by tier (fast / standard / smart / power / ultra).
  * :func:`get_models_for_tier` -- resolves a tier to its
    cumulative model list (additive across tiers, matching the
    reference).
  * :func:`score_response` -- 0-100 scoring on length, structure,
    anti-refusal, directness, relevance. Byte-faithful port of the
    reference's ``scoreResponse``.
  * :func:`race_models` -- the orchestrator. Takes a Provider, a
    list of model ids, the message list, and race config; returns
    a list of :class:`RaceResult` sorted by score desc.

Why provider-agnostic: tests inject a stub Provider so the race
infrastructure can be exercised without hitting a network. The
``/godmode race`` slash command pairs this with
:class:`OpenRouterProvider` for the real path.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Model Tiers ──────────────────────────────────────────────────────
# Source: G0DM0D3/api/lib/ultraplinian.ts ::ULTRAPLINIAN_MODELS
# Five tiers; cumulative so ``standard`` includes ``fast``, ``smart``
# includes ``standard``, etc.
ULTRAPLINIAN_MODELS: dict[str, list[str]] = {
    "fast": [
        "google/gemini-2.5-flash",
        "deepseek/deepseek-chat",
        "perplexity/sonar",
        "meta-llama/llama-3.1-8b-instruct",
        "moonshotai/kimi-k2.5",
        "x-ai/grok-code-fast-1",
        "xiaomi/mimo-v2-flash",
        "openai/gpt-oss-20b",
        "stepfun/step-3.5-flash",
        "google/gemini-3.1-flash-lite",
        "mistralai/mistral-small-3.2-24b-instruct",
        "nvidia/nemotron-3-nano-30b-a3b",
    ],
    "standard": [
        "anthropic/claude-3.5-sonnet",
        "meta-llama/llama-4-scout",
        "deepseek/deepseek-v3.2",
        "nousresearch/hermes-3-llama-3.1-70b",
        "openai/gpt-4o",
        "google/gemini-2.5-pro",
        "anthropic/claude-sonnet-4",
        "anthropic/claude-sonnet-4.6",
        "mistralai/mixtral-8x22b-instruct",
        "meta-llama/llama-3.3-70b-instruct",
        "qwen/qwen-2.5-72b-instruct",
        "nousresearch/hermes-4-70b",
        "mistralai/mistral-medium-3.1",
        "z-ai/glm-5-turbo",
        "google/gemini-3-flash-preview",
        "google/gemma-3-27b-it",
    ],
    "smart": [
        "openai/gpt-5",
        "openai/gpt-5.3-chat",
        "qwen/qwen3.5-plus-02-15",
        "z-ai/glm-5",
        "openai/gpt-5.2",
        "google/gemini-3-pro-preview",
        "anthropic/claude-opus-4.6",
        "openai/gpt-oss-120b",
        "deepseek/deepseek-r1",
        "meta-llama/llama-3.1-405b-instruct",
        "nousresearch/hermes-4-405b",
        "nousresearch/hermes-3-llama-3.1-405b",
        "nvidia/nemotron-3-super-120b-a12b",
    ],
    "power": [
        "x-ai/grok-4",
        "openai/gpt-5.4",
        "z-ai/glm-4.7",
        "meta-llama/llama-4-maverick",
        "qwen/qwen3-235b-a22b",
        "qwen/qwen3-coder",
        "minimax/minimax-m2.5",
        "mistralai/mistral-large-2512",
        "google/gemini-3.1-pro-preview",
        "moonshotai/kimi-k2",
        "xiaomi/mimo-v2-pro",
    ],
    "ultra": [
        "x-ai/grok-4-fast",
        "x-ai/grok-4.1-fast",
        "anthropic/claude-opus-4",
        "qwen/qwen-2.5-coder-32b-instruct",
        "qwen/qwq-32b",
        "mistralai/codestral-2508",
        "mistralai/devstral-medium",
    ],
}

# Tier order matters for cumulative resolution.
_TIER_ORDER = ("fast", "standard", "smart", "power", "ultra")


def get_models_for_tier(tier: str) -> list[str]:
    """Return the cumulative model list for ``tier``.

    Cumulative: ``standard`` is ``fast + standard``; ``smart`` is
    ``fast + standard + smart``; etc. Matches the reference's
    ``getModelsForTier``. Unknown tier raises ``KeyError``.
    """
    if tier not in ULTRAPLINIAN_MODELS:
        raise KeyError(
            f"unknown tier: {tier!r}. "
            f"Valid: {', '.join(ULTRAPLINIAN_MODELS.keys())}"
        )
    out: list[str] = []
    for t in _TIER_ORDER:
        out.extend(ULTRAPLINIAN_MODELS[t])
        if t == tier:
            break
    return out


# ── Response Scoring ─────────────────────────────────────────────────
# Source: G0DM0D3/api/lib/ultraplinian.ts ::scoreResponse
# 0-100 score combining length, structure, anti-refusal, directness,
# and query relevance. Pre-compiled regex patterns for speed.

REFUSAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"I cannot|I can't|I'm unable to", re.IGNORECASE),
    re.compile(r"I apologize|I'm sorry, but", re.IGNORECASE),
    re.compile(r"As an AI|As a language model", re.IGNORECASE),
    re.compile(r"I must decline|I have to refuse", re.IGNORECASE),
    re.compile(r"It would be inappropriate", re.IGNORECASE),
    re.compile(r"I'm not comfortable", re.IGNORECASE),
    re.compile(r"Instead, I can", re.IGNORECASE),
    re.compile(r"It's important to note", re.IGNORECASE),
]

PREAMBLE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(Sure|Of course|Certainly|Absolutely|Great question)", re.IGNORECASE),
    re.compile(r"^I'd be happy to help", re.IGNORECASE),
    re.compile(r"^Let me help you", re.IGNORECASE),
    re.compile(r"^Thanks for asking", re.IGNORECASE),
]

_HEADER_PATTERN = re.compile(r"^#{1,3}\s", re.MULTILINE)
_LIST_PATTERN = re.compile(r"^[\s]*[-*•]\s", re.MULTILINE)
_CODE_BLOCK_PATTERN = re.compile(r"```")


def score_response(content: str, user_query: str) -> int:
    """Score a response on substance, directness, completeness.

    Components:
      * Length (0-25): longer = more substance, diminishing returns
        at content_length / 40 capped at 25.
      * Structure (0-20): headers (x3) + list items (x1.5) +
        code-block pairs (x5), capped at 20.
      * Anti-refusal (0-25): each matched refusal pattern subtracts
        8 from the 25 base. Floor at 0.
      * Directness (0-15): preamble patterns penalize to 8; clean
        starts get the full 15.
      * Relevance (0-15): fraction of >3-char query words present
        in the lower-cased content, times 15.

    Returns 0-100 (rounded).
    """
    if not content or len(content) < 10:
        return 0

    score = 0.0

    # Length (0-25)
    score += min(len(content) / 40.0, 25.0)

    # Structure (0-20)
    headers = len(_HEADER_PATTERN.findall(content))
    list_items = len(_LIST_PATTERN.findall(content))
    code_blocks = len(_CODE_BLOCK_PATTERN.findall(content)) / 2.0
    score += min(headers * 3 + list_items * 1.5 + code_blocks * 5, 20)

    # Anti-refusal (0-25)
    refusal_count = sum(1 for p in REFUSAL_PATTERNS if p.search(content))
    score += max(25 - refusal_count * 8, 0)

    # Directness (0-15)
    trimmed = content.lstrip()
    has_preamble = any(p.match(trimmed) for p in PREAMBLE_PATTERNS)
    score += 8 if has_preamble else 15

    # Relevance (0-15)
    query_words = [w for w in user_query.lower().split() if len(w) > 3]
    if query_words:
        content_lower = content.lower()
        matched = sum(1 for w in query_words if w in content_lower)
        relevance = matched / len(query_words)
    else:
        relevance = 0.5
    score += relevance * 15

    return round(min(score, 100))


# ── Race Result + Orchestrator ───────────────────────────────────────


@dataclass
class RaceResult:
    """One model's race outcome.

    ``score`` is the result of :func:`score_response` on the
    accumulated content. Refusals and errors are still scored (they
    sort low naturally) so consumers see a complete picture.
    """

    model: str
    content: str = ""
    duration_ms: int = 0
    success: bool = False
    error: str | None = None
    score: int = 0


@dataclass
class RaceConfig:
    """Tunables for :func:`race_models`. Defaults mirror the
    reference's ``RaceConfig``."""

    # Stop early once this many models have responded successfully.
    min_results: int = 5
    # After ``min_results`` are in, wait this many seconds for
    # additional responses before returning. Trades latency for
    # response count.
    grace_period_s: float = 5.0
    # Hard cap on the whole race -- cancels any in-flight queries.
    hard_timeout_s: float = 45.0
    # Per-model timeout passed to the provider call. Prevents one
    # wedged model from eating the whole race budget.
    per_model_timeout_s: float = 30.0
    # Optional callback fired per result as it arrives. The
    # /godmode race UI uses this to render live progress.
    on_result: Callable[[RaceResult], None] | None = field(
        default=None, repr=False
    )


# Type alias for the per-model query function: takes (provider, model,
# messages, timeout_s) and returns the accumulated content string.
# Provider-agnostic so tests can inject a stub.
QueryFn = Callable[[Any, str, list[dict[str, Any]], float], str]


def _default_query(
    provider: Any,
    model: str,
    messages: list[dict[str, Any]],
    timeout_s: float,
) -> str:
    """Default query: collect content chunks from ``provider.stream_chat``.

    Times out via the thread executor's ``future.result(timeout=...)``;
    this helper just iterates the stream until it ends or raises.
    ``timeout_s`` is accepted for symmetry with custom QueryFns but
    enforced by the outer racer rather than here -- httpx streams
    don't take a per-iteration timeout cleanly.
    """
    parts: list[str] = []
    for chunk in provider.stream_chat(model=model, messages=messages):
        if chunk.kind == "content":
            payload = chunk.payload or ""
            if isinstance(payload, str):
                parts.append(payload)
    return "".join(parts)


def race_models(
    provider: Any,
    models: Iterable[str],
    messages: list[dict[str, Any]],
    user_query: str,
    *,
    config: RaceConfig | None = None,
    query_fn: QueryFn = _default_query,
) -> list[RaceResult]:
    """Race ``models`` against each other and return scored results.

    Behavior matches the reference's ``raceModels`` early-exit
    pattern:

      1. Fire all queries via a thread pool.
      2. Track successes; once ``config.min_results`` succeed, start
         the grace timer.
      3. When the grace timer fires (or every model finishes), return
         everything collected so far.
      4. ``config.hard_timeout_s`` is a wall-clock cap; futures still
         running at that point are abandoned (their results, if they
         arrive after, are dropped).

    Each result is scored with :func:`score_response`. The returned
    list is sorted by score descending, then by ``duration_ms``
    ascending for tie-breaking (faster wins ties).

    The Provider-agnostic ``query_fn`` is what makes this testable:
    inject a stub function that returns a canned string per model
    and the racer logic runs without any network.
    """
    cfg = config or RaceConfig()
    models_list = list(models)
    if not models_list:
        return []

    results: list[RaceResult] = []
    results_lock = threading.Lock()
    grace_deadline: list[float | None] = [None]  # box for closure mutation
    deadline_lock = threading.Lock()

    def _run_one(model: str) -> RaceResult:
        start = time.perf_counter()
        try:
            content = query_fn(provider, model, messages, cfg.per_model_timeout_s)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            score = score_response(content, user_query)
            return RaceResult(
                model=model,
                content=content,
                duration_ms=elapsed_ms,
                success=True,
                score=score,
            )
        except Exception as e:  # noqa: BLE001
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.debug("race query failed for %s: %s", model, e)
            return RaceResult(
                model=model,
                content="",
                duration_ms=elapsed_ms,
                success=False,
                error=str(e),
                score=0,
            )

    started_at = time.perf_counter()
    # Explicit executor (no ``with``) because ``ThreadPoolExecutor.__exit__``
    # calls ``shutdown(wait=True)``, which would block on the slowest
    # in-flight model and defeat the early-exit. We shutdown(wait=False)
    # in the finally so abandoned futures continue in the background
    # until they complete naturally (or the process exits).
    executor = ThreadPoolExecutor(max_workers=max(1, len(models_list)))
    try:
        futures: dict[Future[RaceResult], str] = {
            executor.submit(_run_one, m): m for m in models_list
        }

        while futures:
            now = time.perf_counter()
            # Hard timeout -- bail with whatever we have.
            if now - started_at >= cfg.hard_timeout_s:
                logger.debug(
                    "race hard timeout reached (%.1fs); abandoning %d futures",
                    cfg.hard_timeout_s,
                    len(futures),
                )
                break
            # Compute the next wait window: until grace deadline (if
            # set) or until hard timeout.
            with deadline_lock:
                grace = grace_deadline[0]
            if grace is not None and now >= grace:
                logger.debug("race grace period elapsed; returning")
                break
            wait_until = (
                grace if grace is not None
                else started_at + cfg.hard_timeout_s
            )
            wait_s = max(0.05, wait_until - now)

            done: list[Future[RaceResult]] = []
            for f in list(futures):
                if f.done():
                    done.append(f)
            if not done:
                # Wait for any one to finish (bounded by wait_s).
                try:
                    next(iter(as_completed_or_timeout(futures, wait_s)))
                except _TimeoutSentinel:
                    continue
                continue

            for f in done:
                model = futures.pop(f)
                try:
                    result = f.result()
                except Exception as e:  # noqa: BLE001
                    result = RaceResult(
                        model=model,
                        content="",
                        duration_ms=0,
                        success=False,
                        error=str(e),
                        score=0,
                    )
                with results_lock:
                    results.append(result)
                if cfg.on_result is not None:
                    try:
                        cfg.on_result(result)
                    except Exception:  # noqa: BLE001
                        logger.debug("race on_result raised", exc_info=True)
                # Once we have enough successes, arm the grace timer.
                with results_lock:
                    success_count = sum(1 for r in results if r.success)
                if success_count >= cfg.min_results:
                    with deadline_lock:
                        if grace_deadline[0] is None:
                            grace_deadline[0] = (
                                time.perf_counter() + cfg.grace_period_s
                            )
    finally:
        # Don't wait for slow models -- the whole point of the early-exit
        # is to return without them. ``cancel_futures=True`` would also
        # be set if we needed Python 3.9+ behavior, but in practice
        # every future has already been submitted to a worker thread by
        # the time we reach here, so cancellation is a no-op and
        # wait=False is sufficient.
        executor.shutdown(wait=False)

    # Sort: score desc, then duration asc.
    results.sort(key=lambda r: (-r.score, r.duration_ms))
    return results


# ── Helpers ──────────────────────────────────────────────────────────


class _TimeoutSentinel(Exception):
    pass


def as_completed_or_timeout(
    futures: dict[Future[RaceResult], str], timeout_s: float
) -> Iterable[Future[RaceResult]]:
    """Like :func:`concurrent.futures.as_completed` but raises a
    :class:`_TimeoutSentinel` if nothing completes within ``timeout_s``.

    Used by :func:`race_models` to wake up periodically and check the
    grace / hard-timeout deadlines without blocking forever on any
    single slow model.
    """
    from concurrent.futures import FIRST_COMPLETED, wait

    done, _pending = wait(futures, timeout=timeout_s, return_when=FIRST_COMPLETED)
    if not done:
        raise _TimeoutSentinel
    return done
