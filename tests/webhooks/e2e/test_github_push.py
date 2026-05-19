"""End-to-end: simulated GitHub push webhook through the full path.

GitHub fires X-Hub-Signature-256 + X-GitHub-Event headers + a JSON
payload. The test:

1. Registers a webhook bound to a "summarize-changes" skill.
2. POSTs a realistic push payload signed with the configured secret.
3. Verifies: 202 returned immediately, dispatch fired with the
   right payload + headers, fire_count incremented.

Uses the same in-process test client other webhook tests use — the
goal is to exercise the wiring (auth + headers + JSON parse +
dispatch + record_fire), not to spin up real Docker or DNS.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from athena.webhooks.delivery import dispatch_webhook
from athena.webhooks.server import WebhookServer
from athena.webhooks.subscription import WebhookStore, WebhookSubscription

# A small realistic GitHub push payload — trimmed to the fields most
# webhook consumers actually care about.
_GITHUB_PUSH_PAYLOAD = {
    "ref": "refs/heads/main",
    "before": "abc123",
    "after": "def456",
    "repository": {
        "full_name": "athena/test-repo",
        "html_url": "https://github.com/athena/test-repo",
    },
    "pusher": {"name": "alice", "email": "alice@example.com"},
    "commits": [
        {
            "id": "def456",
            "message": "fix: handle empty body in webhook",
            "url": "https://github.com/athena/test-repo/commit/def456",
            "author": {"name": "alice", "email": "alice@example.com"},
            "added": ["athena/webhooks/server.py"],
            "modified": ["tests/webhooks/test_server.py"],
            "removed": [],
        },
    ],
    "head_commit": {
        "message": "fix: handle empty body in webhook",
        "author": {"name": "alice"},
    },
}


class _StubAgent:
    def __init__(self, response: str) -> None:
        self.response = response
        self.run_calls: list[str] = []

    def run_until_done(self, prompt: str = "", **_kw) -> None:
        self.run_calls.append(prompt)

    def last_assistant_message(self) -> str:
        return self.response

    def close(self) -> None:
        pass


def _hmac_sig(body: bytes, secret: str) -> str:
    return (
        "sha256="
        + hmac.new(
            secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
    )


async def test_github_push_signature_verified_and_dispatched(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The canonical Phase 15 scenario: a GitHub push hits the
    listener, the signature verifies, the agent runs the bound skill
    with the parsed payload + filtered headers, the response logs."""
    store = WebhookStore(tmp_path / "webhooks.db")
    secret = "shared-with-github"
    sub = WebhookSubscription(
        description="GitHub push → summarize",
        auth_type="hmac_sha256",
        auth_secret=secret,
        binding_type="skill",
        skill_name="summarize-changes",
        delivery_target="log",
    )
    store.add(sub)

    agent_response = "alice pushed 1 commit: fix: handle empty body"
    dispatched_with: list[tuple] = []

    async def real_dispatch(s, payload, headers):
        agent = _StubAgent(agent_response)
        await dispatch_webhook(
            daemon=None,
            sub=s,
            payload=payload,
            headers=headers,
            agent_factory=lambda: agent,
        )
        dispatched_with.append((s.id, payload, headers, agent.run_calls))

    server = WebhookServer(
        daemon=None,
        store=store,
        host="127.0.0.1",
        port=0,
        dispatch=real_dispatch,
    )

    async with TestClient(TestServer(server.app)) as client:
        body = json.dumps(_GITHUB_PUSH_PAYLOAD).encode("utf-8")
        sig = _hmac_sig(body, secret)
        resp = await client.post(
            f"/webhook/{sub.id}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "delivery-abc-123",
                "User-Agent": "GitHub-Hookshot/abc123",
                "X-Webhook-Idempotency-Key": "delivery-abc-123",
            },
        )
        assert resp.status == 202

        # Give the spawned dispatch task time to land.
        for _ in range(50):
            if dispatched_with:
                break
            await asyncio.sleep(0.02)

    assert len(dispatched_with) == 1
    sid, payload, headers, run_calls = dispatched_with[0]
    assert sid == sub.id
    # Payload survived JSON parse intact.
    assert payload["ref"] == "refs/heads/main"
    assert payload["repository"]["full_name"] == "athena/test-repo"
    assert payload["pusher"]["name"] == "alice"
    # Filtered headers carried through.
    assert headers["X-GitHub-Event"] == "push"
    assert headers["X-GitHub-Delivery"] == "delivery-abc-123"
    # Auth headers stripped.
    assert "X-Hub-Signature-256" not in headers
    # The agent saw a prompt mentioning the skill and the push details.
    assert run_calls
    prompt = run_calls[0]
    assert "summarize-changes" in prompt
    assert "refs/heads/main" in prompt
    assert "alice" in prompt
    # fire_count incremented.
    assert store.get(sub.id).fire_count == 1


async def test_github_push_wrong_signature_rejected(tmp_path: Path) -> None:
    """A push signed with the wrong secret never reaches dispatch."""
    store = WebhookStore(tmp_path / "webhooks.db")
    sub = WebhookSubscription(
        auth_type="hmac_sha256",
        auth_secret="correct",
        skill_name="summarize-changes",
    )
    store.add(sub)

    fired: list[tuple] = []

    async def spy_dispatch(s, payload, headers):
        fired.append((s.id, payload, headers))

    server = WebhookServer(
        daemon=None,
        store=store,
        host="127.0.0.1",
        port=0,
        dispatch=spy_dispatch,
    )

    async with TestClient(TestServer(server.app)) as client:
        body = json.dumps(_GITHUB_PUSH_PAYLOAD).encode("utf-8")
        # Sign with the WRONG secret.
        bad_sig = _hmac_sig(body, "attacker-guess")
        resp = await client.post(
            f"/webhook/{sub.id}",
            data=body,
            headers={
                "X-Hub-Signature-256": bad_sig,
                "X-GitHub-Event": "push",
            },
        )

    assert resp.status == 401
    await asyncio.sleep(0.05)
    assert fired == []
    assert store.get(sub.id).fire_count == 0


async def test_github_redelivery_idempotent(tmp_path: Path) -> None:
    """GitHub retries on timeout. Same delivery id → second POST
    short-circuits to 200 no-op."""
    store = WebhookStore(tmp_path / "webhooks.db")
    secret = "s"
    sub = WebhookSubscription(
        auth_type="hmac_sha256",
        auth_secret=secret,
        skill_name="echo",
    )
    store.add(sub)

    dispatches: list = []

    async def spy(s, p, h):
        dispatches.append(s.id)

    server = WebhookServer(
        daemon=None,
        store=store,
        host="127.0.0.1",
        port=0,
        dispatch=spy,
    )

    body = json.dumps(_GITHUB_PUSH_PAYLOAD).encode("utf-8")
    headers = {
        "X-Hub-Signature-256": _hmac_sig(body, secret),
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "abc-delivery",
        "X-Webhook-Idempotency-Key": "abc-delivery",
    }
    async with TestClient(TestServer(server.app)) as client:
        r1 = await client.post(
            f"/webhook/{sub.id}",
            data=body,
            headers=headers,
        )
        r2 = await client.post(
            f"/webhook/{sub.id}",
            data=body,
            headers=headers,
        )

    assert r1.status == 202
    assert r2.status == 200  # duplicate; no-op
    await asyncio.sleep(0.05)
    assert len(dispatches) == 1  # agent fired only once
