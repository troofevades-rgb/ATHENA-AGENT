"""Tests for 429-driven credential rotation (wired in Phase 17.6).

Architecture:

  1. ``error_classifier.classify`` keeps 429 → ``ErrorAction.RETRY``
     (single-key users benefit from backoff alone). The classifier
     stays pure / stateless.
  2. ``retry_utils.with_retry`` tracks consecutive 429s and escalates
     to ``ROTATE_CREDENTIAL`` after 2 in a row when an
     ``on_rotate_credential`` callback is provided.
  3. Each hosted provider (anthropic, openai/openrouter/nous/openai_compat
     via OpenAICompatibleProvider, google) declares a
     ``_rotate_credential`` method that consults the injected
     ``credential_pool``, marks the current key as 429'd, asks for
     the next one, and mutates the httpx client's auth header in
     place.
  4. ``runtime_resolver._build_provider`` passes the pool into the
     provider constructor at instantiation time.

The static and runtime checks below ensure no provider regresses to
the pre-Phase-17.6 state where rotation was advertised in CLAUDE.md
but didn't actually fire.

The integration tests at the bottom drive the COMPONENTS end-to-end
to prove the wire from pool ↔ retry ↔ provider works.
"""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest

from athena.providers.credential_pool import Credential, CredentialPool
from athena.providers.error_classifier import ErrorAction, classify
from athena.providers.retry_utils import RetryBudgetExceeded, with_retry


REPO_ROOT = Path(__file__).resolve().parents[2]
PROVIDERS_DIR = REPO_ROOT / "athena" / "providers"

# The five hosted providers that authenticate with an API key and could
# benefit from rotation. (ollama / openai_compat work without a key.)
_HOSTED_PROVIDERS = ("anthropic", "openai", "google", "openrouter", "nous")


# ---------------------------------------------------------------------------
# Classifier pins: 429 maps to RETRY at the classifier layer
# (with_retry layer escalates to ROTATE_CREDENTIAL after N consecutive 429s)
# ---------------------------------------------------------------------------


def _http_status_error(code: int, *, headers: dict[str, str] | None = None) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://example.com/v1/messages")
    resp = httpx.Response(code, headers=headers or {}, request=req)
    return httpx.HTTPStatusError(f"{code}", request=req, response=resp)


def test_classifier_returns_RETRY_for_429() -> None:
    """The classifier keeps mapping 429 to ``ErrorAction.RETRY`` —
    escalation to ROTATE_CREDENTIAL lives in ``retry_utils.with_retry``
    (after N consecutive 429s), not in the classifier. This keeps
    the classifier pure and stateless."""
    err = _http_status_error(429, headers={"retry-after": "1"})
    c = classify(err)
    assert c.action == ErrorAction.RETRY


def test_classifier_returns_RETRY_for_429_without_retry_after() -> None:
    """429 without a Retry-After header also maps to RETRY (with
    exponential backoff). Same rotation-unreachable story."""
    err = _http_status_error(429)
    c = classify(err)
    assert c.action == ErrorAction.RETRY


def test_classifier_never_returns_ROTATE_CREDENTIAL_for_any_http_status() -> None:
    """Confirm the broader claim — no HTTP-status path leads to
    ROTATE_CREDENTIAL today. If any path starts returning it, the
    wiring gap below MUST be fixed in the same change or the agent
    will hard-fail on those codes."""
    for code in (400, 401, 403, 408, 429, 500, 502, 503, 504):
        c = classify(_http_status_error(code))
        assert c.action != ErrorAction.ROTATE_CREDENTIAL, (
            f"HTTP {code} now classifies as ROTATE_CREDENTIAL — "
            f"providers MUST be updated to pass on_rotate_credential "
            f"to with_retry, or every {code} will surface as an abort"
        )


# ---------------------------------------------------------------------------
# Wiring: every hosted provider with retry MUST pass on_rotate_credential
# ---------------------------------------------------------------------------


def _ast_find_calls(tree: ast.AST, func_name: str) -> list[ast.Call]:
    """Return every Call node whose function name (last attr) matches."""
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        if name == func_name:
            found.append(node)
    return found


def _has_kwarg(call: ast.Call, kwname: str) -> bool:
    return any(kw.arg == kwname for kw in call.keywords)


@pytest.mark.parametrize("provider_name", _HOSTED_PROVIDERS)
def test_provider_with_retry_call_passes_rotate_callback(
    provider_name: str,
) -> None:
    """Static check (Phase 17.6 wiring): every provider that uses
    ``with_retry`` MUST pass ``on_rotate_credential=`` so the rotate
    callback fires when the classifier escalates consecutive 429s
    to ROTATE_CREDENTIAL.

    Skipped for providers that don't use with_retry — those have an
    independent gap (no retry at all) that will be addressed later."""
    path = PROVIDERS_DIR / f"{provider_name}.py"
    if not path.exists():
        pytest.skip(f"{provider_name}.py not present")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = _ast_find_calls(tree, "with_retry")
    if not calls:
        pytest.skip(f"{provider_name} does not use with_retry")
    for call in calls:
        assert _has_kwarg(call, "on_rotate_credential"), (
            f"{provider_name}.py: with_retry call missing "
            f"on_rotate_credential — 429 rotation will not fire"
        )


def test_every_hosted_provider_has_rotate_helper() -> None:
    """All 5 hosted providers must EXPOSE ``_rotate_credential`` (via
    direct declaration or inheritance) so the runtime-resolver-injected
    ``credential_pool`` is actually consulted on 429.

    Runtime check — covers the inheritance path (openrouter/nous/
    openai_compat inherit from OpenAICompatibleProvider)."""
    from athena.providers.anthropic import AnthropicProvider
    from athena.providers.google import GoogleProvider
    from athena.providers.nous import NousProvider
    from athena.providers.openai import OpenAIProvider
    from athena.providers.openai_compat import OpenAICompatProvider
    from athena.providers.openrouter import OpenRouterProvider

    classes = [
        ("anthropic", AnthropicProvider),
        ("openai", OpenAIProvider),
        ("google", GoogleProvider),
        ("openrouter", OpenRouterProvider),
        ("nous", NousProvider),
        ("openai_compat", OpenAICompatProvider),
    ]
    missing = [
        name for name, cls in classes
        if not hasattr(cls, "_rotate_credential")
    ]
    assert not missing, (
        f"providers missing _rotate_credential helper: {missing}. "
        f"Rotation will silently no-op for these."
    )


# ---------------------------------------------------------------------------
# Integration — components compose end-to-end through with_retry
# ---------------------------------------------------------------------------


def test_components_wired_manually_rotate_on_repeated_429(
    tmp_path: Path,
) -> None:
    """Prove the building blocks work TOGETHER when connected — so we
    know wiring is the only thing missing, not a deeper bug.

    Setup: a pool with two credentials, an operation that 429s on the
    first credential and succeeds on the second. with_retry's
    ``on_rotate_credential`` callback bridges them. The classifier
    won't naturally return ROTATE_CREDENTIAL for 429, so the test
    forces that with a fake operation that raises an exception the
    classifier maps to ROTATE_CREDENTIAL — or, since none exist,
    drives the rotation via the budget-exceeded path with retries=0
    and a custom failure-then-success operation."""
    pool = CredentialPool(config_path=tmp_path / "creds.json")
    pool.add_credential("anthropic", Credential(key="sk-ant-AAAAAAAA"))
    pool.add_credential("anthropic", Credential(key="sk-ant-BBBBBBBB"))

    # Operation simulates a provider call. First call: 429 on whichever
    # cred is in use. Second call (after rotation): success.
    current_key: list[str] = [pool.get("anthropic").key]
    op_attempts: list[str] = []

    def operation() -> str:
        op_attempts.append(current_key[0])
        if current_key[0].endswith("AAAAAAAA"):
            raise _http_status_error(429, headers={"retry-after": "0"})
        return "ok"

    def on_rotate() -> bool:
        pool.mark_429("anthropic", current_key[0])
        nxt = pool.rotate_to_next("anthropic")
        if nxt is None:
            return False
        current_key[0] = nxt.key
        return True

    # The classifier won't escalate 429 to ROTATE_CREDENTIAL today
    # (see gap 1 tests above), so we drive the rotation manually here
    # to prove the components compose correctly.
    with pytest.raises(httpx.HTTPStatusError):
        operation()
    assert on_rotate() is True, (
        "rotate_to_next returned None despite having a second cred — "
        "pool/cooldown logic broken"
    )
    assert operation() == "ok"
    assert op_attempts[0].endswith("AAAAAAAA")
    assert op_attempts[1].endswith("BBBBBBBB")


def test_with_retry_invokes_rotate_callback_when_classifier_returns_rotate(
    tmp_path: Path,
) -> None:
    """If we manually raise an exception that the classifier maps to
    ROTATE_CREDENTIAL, ``with_retry`` correctly invokes the callback.

    No such exception exists in the classifier today (gap 1), so we
    monkey-patch the classifier inside the test to prove the wiring
    in with_retry itself is correct."""
    from athena.providers import error_classifier as _ec
    from athena.providers import retry_utils as _ru

    pool = CredentialPool(config_path=tmp_path / "creds.json")
    pool.add_credential("anthropic", Credential(key="sk-ant-XXXXXXXX"))
    pool.add_credential("anthropic", Credential(key="sk-ant-YYYYYYYY"))

    rotate_invocations: list[bool] = []

    def on_rotate() -> bool:
        pool.mark_429("anthropic", pool.get("anthropic").key)
        nxt = pool.rotate_to_next("anthropic")
        rotate_invocations.append(nxt is not None)
        return nxt is not None

    # Inject a classifier that always says ROTATE_CREDENTIAL once
    call_count = [0]
    def _fake_classify(exc, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return _ec.Classification(
                action=_ec.ErrorAction.ROTATE_CREDENTIAL,
                error_class=_ec.ErrorClass.RATE_LIMIT,
                reason="synthesized rotate signal for test",
                suggested_backoff_s=0.0,
            )
        return _ec.Classification(
            action=_ec.ErrorAction.ABORT,
            error_class=_ec.ErrorClass.UNKNOWN,
            reason="stop now",
            suggested_backoff_s=0.0,
        )

    op_calls = [0]
    def operation() -> str:
        op_calls[0] += 1
        if op_calls[0] == 1:
            raise _http_status_error(429)
        return "rotated ok"

    import unittest.mock as _mock
    with _mock.patch.object(_ru, "_classify_from_exc", _fake_classify):
        result = with_retry(
            operation,
            on_rotate_credential=on_rotate,
            max_retries=3,
            max_backoff_s=0.01,
        )

    assert result == "rotated ok"
    assert rotate_invocations == [True], (
        "rotate callback was not invoked despite ROTATE_CREDENTIAL action — "
        "with_retry's rotation wiring is broken"
    )


def test_pool_rotates_when_first_credential_429s(tmp_path: Path) -> None:
    """End-to-end pool behavior: mark cred A as 429'd, request the
    next one, verify it's a different cred. This is what the missing
    wiring would do."""
    pool = CredentialPool(config_path=tmp_path / "creds.json")
    pool.add_credential("anthropic", Credential(key="sk-ant-1111"))
    pool.add_credential("anthropic", Credential(key="sk-ant-2222"))
    pool.add_credential("anthropic", Credential(key="sk-ant-3333"))

    first = pool.get("anthropic")
    assert first is not None
    assert pool.mark_429("anthropic", first.key) is True

    next_cred = pool.rotate_to_next("anthropic")
    assert next_cred is not None
    assert next_cred.key != first.key, "rotation returned the same key"


def test_pool_returns_none_when_all_creds_in_cooldown(tmp_path: Path) -> None:
    """The worst case worth pinning: every credential is in 429
    cooldown. ``rotate_to_next`` must return None so the caller can
    surface a clean "no credentials available" error rather than
    spinning forever."""
    pool = CredentialPool(config_path=tmp_path / "creds.json")
    keys = ["sk-ant-AAAA", "sk-ant-BBBB"]
    for k in keys:
        pool.add_credential("anthropic", Credential(key=k))

    for k in keys:
        pool.mark_429("anthropic", k)

    assert pool.rotate_to_next("anthropic") is None


# ---------------------------------------------------------------------------
# Real provider end-to-end — rotates Authorization header on 429
# ---------------------------------------------------------------------------


def test_openai_provider_rotates_auth_header_on_consecutive_429s(
    tmp_path: Path,
) -> None:
    """Drive OpenAIProvider with a mock httpx transport that returns
    429 for the first two requests and 200 for the third. Pool has
    two credentials. After the second 429, the rotate callback
    should swap the Authorization header — the third request goes
    out with key B and succeeds.

    This is the actual production path: provider → with_retry →
    classifier escalation → on_rotate_credential → pool → header
    mutation → next attempt."""
    from athena.providers.credential_pool import Credential, CredentialPool
    from athena.providers.openai import OpenAIProvider

    pool = CredentialPool(config_path=tmp_path / "creds.json")
    pool.add_credential("openai", Credential(key="sk-AAAA-key-aaa"))
    pool.add_credential("openai", Credential(key="sk-BBBB-key-bbb"))

    seen_auth_headers: list[str] = []
    call_count = [0]

    def _handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers.get("authorization", ""))
        call_count[0] += 1
        if call_count[0] <= 2:
            # First two requests: 429
            return httpx.Response(
                429,
                headers={"retry-after": "0"},
                json={"error": {"message": "rate limit"}},
            )
        # Third request: minimal valid streaming-shaped response
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    transport = httpx.MockTransport(_handler)
    # Start with the first cred from the pool
    first_cred = pool.get("openai")
    assert first_cred is not None
    provider = OpenAIProvider(
        api_key=first_cred.key,
        credential_pool=pool,
    )
    # Replace the auto-built client with one bound to the mock transport
    provider._client = httpx.Client(
        base_url=provider.base_url,
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {first_cred.key}",
        },
        transport=transport,
    )
    provider._retry_max = 5
    provider._retry_backoff_s = 0.01

    # Consume the stream — the chunks themselves don't matter; what
    # matters is that the third underlying HTTP request used a
    # DIFFERENT Authorization header than the first two.
    list(provider.stream_chat(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
    ))

    assert call_count[0] == 3, (
        f"expected 3 underlying requests (2 × 429 + 1 success); "
        f"got {call_count[0]}"
    )
    assert seen_auth_headers[0].endswith("aaa"), (
        f"first request used wrong key: {seen_auth_headers[0]!r}"
    )
    assert seen_auth_headers[1].endswith("aaa"), (
        f"second request (pre-rotation) used wrong key: {seen_auth_headers[1]!r}"
    )
    assert seen_auth_headers[2].endswith("bbb"), (
        f"third request did NOT use the rotated key — rotation "
        f"didn't take effect. Got: {seen_auth_headers[2]!r}"
    )


def test_anthropic_provider_rotates_x_api_key_on_consecutive_429s(
    tmp_path: Path,
) -> None:
    """Same end-to-end test for AnthropicProvider, which uses
    ``x-api-key`` instead of ``Authorization: Bearer``."""
    from athena.providers.anthropic import AnthropicProvider
    from athena.providers.credential_pool import Credential, CredentialPool

    pool = CredentialPool(config_path=tmp_path / "creds.json")
    pool.add_credential("anthropic", Credential(key="sk-ant-AAA1"))
    pool.add_credential("anthropic", Credential(key="sk-ant-BBB2"))

    seen_keys: list[str] = []
    call_count = [0]

    def _handler(request: httpx.Request) -> httpx.Response:
        seen_keys.append(request.headers.get("x-api-key", ""))
        call_count[0] += 1
        if call_count[0] <= 2:
            return httpx.Response(
                429,
                headers={"retry-after": "0"},
                json={"error": {"message": "rate limit"}},
            )
        # Minimal valid Anthropic SSE: message_stop event
        body = b"event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    transport = httpx.MockTransport(_handler)
    first = pool.get("anthropic")
    assert first is not None
    provider = AnthropicProvider(
        api_key=first.key,
        credential_pool=pool,
    )
    provider._client = httpx.Client(
        base_url=provider.base_url,
        headers={
            "x-api-key": first.key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        transport=transport,
    )
    provider._retry_max = 5
    provider._retry_backoff_s = 0.01

    list(provider.stream_chat(
        model="claude-3-5-sonnet-latest",
        messages=[{"role": "user", "content": "hi"}],
    ))

    assert call_count[0] == 3
    assert seen_keys[0] == "sk-ant-AAA1"
    assert seen_keys[1] == "sk-ant-AAA1"
    assert seen_keys[2] == "sk-ant-BBB2", (
        f"third request did NOT use the rotated key; got {seen_keys[2]!r}"
    )


def test_runtime_resolver_passes_credential_pool_to_provider(
    tmp_path: Path,
) -> None:
    """The runtime resolver wires the pool into the provider at
    instantiation time. Without this, even a provider with the
    correct ``_rotate_credential`` helper would have nothing to
    rotate against. Sanity check on the wiring."""
    from athena.config import Config
    from athena.providers.credential_pool import Credential, CredentialPool
    from athena.providers.runtime_resolver import _build_provider

    pool = CredentialPool(config_path=tmp_path / "creds.json")
    pool.add_credential("openai", Credential(key="sk-test-key"))

    cfg = Config()
    provider, _ = _build_provider("openai", "gpt-4o-mini", cfg=cfg, pool=pool)
    assert provider._credential_pool is pool, (
        "runtime_resolver did not inject the pool into the provider — "
        "rotation will silently no-op even though the helper is wired"
    )
