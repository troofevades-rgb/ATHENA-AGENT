"""WebhookServer — aiohttp listener wiring auth + idempotency + rate
limit + async dispatch."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from athena.webhooks.server import (
    WebhookServer,
    _parse_body,
    _snapshot_headers,
)
from athena.webhooks.subscription import WebhookStore, WebhookSubscription


def _hmac_sig(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def store(tmp_path: Path) -> WebhookStore:
    return WebhookStore(tmp_path / "webhooks.db")


@pytest.fixture
def fake_dispatch():
    """A spy dispatch callback. Tests inspect `.calls` to verify what
    landed."""
    calls: list[tuple] = []

    async def dispatch(sub, payload, headers):
        calls.append((sub.id, payload, headers))

    dispatch.calls = calls  # type: ignore[attr-defined]
    return dispatch


@pytest.fixture
async def server_client(store, fake_dispatch):
    """A live aiohttp TestServer for the webhook listener.

    TestClient lets us POST without binding a real port; the server
    constructs an in-process AppRunner."""
    server = WebhookServer(
        daemon=None,
        store=store,
        host="127.0.0.1",
        port=0,
        dispatch=fake_dispatch,
    )
    # We don't actually start() the server's own AppRunner — the
    # test client wires its own runner around server.app.
    async with TestClient(TestServer(server.app)) as client:
        yield server, client, fake_dispatch


# ---- 404 paths -------------------------------------------------------


async def test_unknown_id_returns_404(server_client) -> None:
    _server, client, _dispatch = server_client
    resp = await client.post("/webhook/never-existed", data=b"{}")
    assert resp.status == 404


async def test_disabled_subscription_returns_404(
    server_client, store,
) -> None:
    _server, client, _dispatch = server_client
    sub = WebhookSubscription(
        skill_name="echo", auth_type="none", auth_secret="",
        enabled=False,
    )
    store.add(sub)
    resp = await client.post(f"/webhook/{sub.id}", data=b"{}")
    assert resp.status == 404


# ---- auth ------------------------------------------------------------


async def test_hmac_correct_signature_dispatches(
    server_client, store,
) -> None:
    server, client, dispatch = server_client
    secret = "shh"
    sub = WebhookSubscription(
        skill_name="echo", auth_type="hmac_sha256", auth_secret=secret,
    )
    store.add(sub)
    body = b'{"event":"push"}'
    sig = _hmac_sig(body, secret)
    resp = await client.post(
        f"/webhook/{sub.id}", data=body,
        headers={"X-Webhook-Signature": sig},
    )
    assert resp.status == 202
    # Give the dispatch task a tick to run.
    await asyncio.sleep(0.02)
    assert len(dispatch.calls) == 1
    sid, payload, _headers = dispatch.calls[0]
    assert sid == sub.id
    assert payload == {"event": "push"}


async def test_hmac_github_style_header_works(
    server_client, store,
) -> None:
    """X-Hub-Signature-256: sha256=<hex> from GitHub."""
    server, client, dispatch = server_client
    secret = "github-secret"
    sub = WebhookSubscription(
        skill_name="echo", auth_type="hmac_sha256", auth_secret=secret,
    )
    store.add(sub)
    body = b'{"ref":"refs/heads/main"}'
    sig = "sha256=" + _hmac_sig(body, secret)
    resp = await client.post(
        f"/webhook/{sub.id}", data=body,
        headers={"X-Hub-Signature-256": sig},
    )
    assert resp.status == 202


async def test_hmac_wrong_signature_returns_401(
    server_client, store,
) -> None:
    _server, client, dispatch = server_client
    sub = WebhookSubscription(
        skill_name="echo", auth_type="hmac_sha256", auth_secret="real",
    )
    store.add(sub)
    resp = await client.post(
        f"/webhook/{sub.id}", data=b"{}",
        headers={"X-Webhook-Signature": "deadbeef" * 8},
    )
    assert resp.status == 401
    await asyncio.sleep(0.02)
    assert dispatch.calls == []  # never dispatched


async def test_missing_signature_returns_401(server_client, store) -> None:
    _server, client, _dispatch = server_client
    sub = WebhookSubscription(
        skill_name="echo", auth_type="hmac_sha256", auth_secret="x",
    )
    store.add(sub)
    resp = await client.post(f"/webhook/{sub.id}", data=b"{}")
    assert resp.status == 401


async def test_bearer_correct_token_dispatches(
    server_client, store,
) -> None:
    server, client, dispatch = server_client
    sub = WebhookSubscription(
        skill_name="echo", auth_type="bearer", auth_secret="tok-1234",
    )
    store.add(sub)
    resp = await client.post(
        f"/webhook/{sub.id}", data=b"{}",
        headers={"Authorization": "Bearer tok-1234"},
    )
    assert resp.status == 202
    await asyncio.sleep(0.02)
    assert len(dispatch.calls) == 1


async def test_bearer_wrong_token_returns_401(
    server_client, store,
) -> None:
    _server, client, _dispatch = server_client
    sub = WebhookSubscription(
        skill_name="echo", auth_type="bearer", auth_secret="real",
    )
    store.add(sub)
    resp = await client.post(
        f"/webhook/{sub.id}", data=b"{}",
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status == 401


async def test_auth_none_accepts_anything(server_client, store) -> None:
    server, client, dispatch = server_client
    sub = WebhookSubscription(
        skill_name="echo", auth_type="none", auth_secret="",
    )
    store.add(sub)
    resp = await client.post(f"/webhook/{sub.id}", data=b"{}")
    assert resp.status == 202
    await asyncio.sleep(0.02)
    assert len(dispatch.calls) == 1


# ---- idempotency ----------------------------------------------------


async def test_idempotency_dedupes_within_ttl(
    server_client, store,
) -> None:
    server, client, dispatch = server_client
    sub = WebhookSubscription(
        skill_name="echo", auth_type="none", auth_secret="",
    )
    store.add(sub)
    headers = {"X-Webhook-Idempotency-Key": "delivery-7"}

    # First call goes through.
    resp1 = await client.post(
        f"/webhook/{sub.id}", data=b"{}", headers=headers,
    )
    assert resp1.status == 202
    # Second call with same key short-circuits to 200 no-op.
    resp2 = await client.post(
        f"/webhook/{sub.id}", data=b"{}", headers=headers,
    )
    assert resp2.status == 200
    text = await resp2.text()
    assert "duplicate" in text

    await asyncio.sleep(0.02)
    # Only one dispatch.
    assert len(dispatch.calls) == 1


async def test_idempotency_different_keys_both_dispatch(
    server_client, store,
) -> None:
    server, client, dispatch = server_client
    sub = WebhookSubscription(
        skill_name="echo", auth_type="none", auth_secret="",
    )
    store.add(sub)
    await client.post(
        f"/webhook/{sub.id}", data=b"{}",
        headers={"X-Webhook-Idempotency-Key": "a"},
    )
    await client.post(
        f"/webhook/{sub.id}", data=b"{}",
        headers={"X-Webhook-Idempotency-Key": "b"},
    )
    await asyncio.sleep(0.02)
    assert len(dispatch.calls) == 2


# ---- rate limit -----------------------------------------------------


async def test_rate_limit_returns_429(server_client, store) -> None:
    server, client, dispatch = server_client
    sub = WebhookSubscription(
        skill_name="echo", auth_type="none", auth_secret="",
        rate_limit_per_minute=2,
    )
    store.add(sub)
    r1 = await client.post(f"/webhook/{sub.id}", data=b"{}")
    r2 = await client.post(f"/webhook/{sub.id}", data=b"{}")
    r3 = await client.post(f"/webhook/{sub.id}", data=b"{}")
    assert r1.status == 202
    assert r2.status == 202
    assert r3.status == 429
    await asyncio.sleep(0.02)
    assert len(dispatch.calls) == 2  # third never dispatched


async def test_rate_limit_per_webhook_isolated(
    server_client, store,
) -> None:
    """One noisy webhook hitting its limit must not block others."""
    server, client, dispatch = server_client
    a = WebhookSubscription(
        skill_name="echo", auth_type="none", auth_secret="",
        rate_limit_per_minute=1,
    )
    b = WebhookSubscription(
        skill_name="echo", auth_type="none", auth_secret="",
        rate_limit_per_minute=5,
    )
    store.add(a)
    store.add(b)

    # a's burst exhausts its budget.
    await client.post(f"/webhook/{a.id}", data=b"{}")
    blocked = await client.post(f"/webhook/{a.id}", data=b"{}")
    assert blocked.status == 429

    # b's first call still works.
    ok = await client.post(f"/webhook/{b.id}", data=b"{}")
    assert ok.status == 202


# ---- body parsing --------------------------------------------------


async def test_json_body_parsed_to_dict(server_client, store) -> None:
    server, client, dispatch = server_client
    sub = WebhookSubscription(
        skill_name="echo", auth_type="none", auth_secret="",
    )
    store.add(sub)
    await client.post(
        f"/webhook/{sub.id}",
        json={"action": "opened", "issue": {"number": 42}},
    )
    await asyncio.sleep(0.02)
    _sid, payload, _ = dispatch.calls[0]
    assert payload == {"action": "opened", "issue": {"number": 42}}


async def test_non_json_body_wrapped_with_format_hint(
    server_client, store,
) -> None:
    server, client, dispatch = server_client
    sub = WebhookSubscription(
        skill_name="echo", auth_type="none", auth_secret="",
    )
    store.add(sub)
    await client.post(
        f"/webhook/{sub.id}", data=b"this is not json",
        headers={"Content-Type": "text/plain"},
    )
    await asyncio.sleep(0.02)
    _sid, payload, _ = dispatch.calls[0]
    assert payload["_raw_body"] == "this is not json"
    assert "non-json" in payload["_format_hint"]


# ---- async dispatch + record_fire ----------------------------------


async def test_202_returned_immediately_even_for_slow_dispatch(
    server_client, store,
) -> None:
    server, client, _dispatch_ignored = server_client

    captured: dict = {}

    async def slow_dispatch(sub, payload, headers):
        # Sleep longer than the test will wait — but the response
        # should have already returned 202.
        captured["before_sleep"] = True
        await asyncio.sleep(0.3)
        captured["after_sleep"] = True

    server.dispatch = slow_dispatch
    sub = WebhookSubscription(
        skill_name="echo", auth_type="none", auth_secret="",
    )
    store.add(sub)

    import time
    start = time.monotonic()
    resp = await client.post(f"/webhook/{sub.id}", data=b"{}")
    elapsed = time.monotonic() - start
    assert resp.status == 202
    # Response must come back well before the slow dispatch finishes.
    assert elapsed < 0.1


async def test_dispatch_exception_does_not_break_subsequent_requests(
    server_client, store,
) -> None:
    server, client, _ = server_client

    async def bad_dispatch(sub, payload, headers):
        raise RuntimeError("simulated crash")

    server.dispatch = bad_dispatch
    sub = WebhookSubscription(
        skill_name="echo", auth_type="none", auth_secret="",
    )
    store.add(sub)
    # First request crashes during dispatch — caller still gets 202.
    r1 = await client.post(f"/webhook/{sub.id}", data=b"{}")
    assert r1.status == 202
    # Second request still works.
    r2 = await client.post(f"/webhook/{sub.id}", data=b"{}")
    assert r2.status == 202


async def test_record_fire_increments_on_dispatch(
    server_client, store,
) -> None:
    server, client, _ = server_client
    sub = WebhookSubscription(
        skill_name="echo", auth_type="none", auth_secret="",
    )
    store.add(sub)
    await client.post(f"/webhook/{sub.id}", data=b"{}")
    await client.post(f"/webhook/{sub.id}", data=b"{}")
    await asyncio.sleep(0.02)
    assert store.get(sub.id).fire_count == 2


# ---- health endpoint ---------------------------------------------


async def test_health_returns_status_ok(server_client) -> None:
    server, client, _ = server_client
    resp = await client.get("/health")
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "ok"


# ---- module-level helpers ---------------------------------------


def test_parse_body_empty_returns_empty_dict() -> None:
    assert _parse_body(b"") == {}


def test_parse_body_valid_json() -> None:
    assert _parse_body(b'{"a": 1}') == {"a": 1}


def test_parse_body_non_utf8_base64_wrapped() -> None:
    binary = b"\xff\xfe\xfd\x00\x01"
    payload = _parse_body(binary)
    assert "_raw_body_base64" in payload
    assert base64.b64decode(payload["_raw_body_base64"]) == binary


def test_parse_body_non_json_text() -> None:
    payload = _parse_body(b"hello world")
    assert payload["_raw_body"] == "hello world"
    assert "non-json" in payload["_format_hint"]


def test_parse_body_top_level_array_wrapped() -> None:
    payload = _parse_body(b'[1, 2, 3]')
    assert payload == {"_top_level": [1, 2, 3]}


def test_snapshot_headers_forwards_known_prefixes() -> None:
    headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "abc-123",
        "Content-Type": "application/json",
        "X-Webhook-Idempotency-Key": "key-1",
        # These get filtered out:
        "Authorization": "Bearer secret",
        "X-Webhook-Signature": "deadbeef",
        "X-Hub-Signature-256": "sha256=...",
        "Random-Header": "ignored",
    }
    out = _snapshot_headers(headers)
    assert out["X-GitHub-Event"] == "push"
    assert out["X-GitHub-Delivery"] == "abc-123"
    assert out["Content-Type"] == "application/json"
    assert out["X-Webhook-Idempotency-Key"] == "key-1"
    assert "Authorization" not in out
    assert "X-Webhook-Signature" not in out
    assert "X-Hub-Signature-256" not in out
    assert "Random-Header" not in out
