"""Webhook dispatch + delivery routing."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from athena.webhooks.delivery import (
    _build_prompt,
    _parse_gateway_target,
    _substitute_template,
    dispatch_webhook,
)
from athena.webhooks.subscription import WebhookSubscription


class _StubAgent:
    """One-off agent stand-in. Records the prompt; returns a canned
    response that callers can inspect after delivery."""

    def __init__(self, response: str = "stub agent response") -> None:
        self.run_calls: list[str] = []
        self.response = response
        self.closed = False

    def run_until_done(
        self,
        prompt: str = "",
        *,
        max_iterations: int | None = None,
    ) -> None:
        self.run_calls.append(prompt)

    def last_assistant_message(self) -> str:
        return self.response

    def close(self) -> None:
        self.closed = True


# ---- _build_prompt --------------------------------------------------


def test_build_prompt_skill_binding() -> None:
    sub = WebhookSubscription(
        skill_name="summarize-pr",
        auth_secret="x",
    )
    prompt = _build_prompt(
        sub,
        payload={"action": "opened", "number": 42},
        headers={"X-GitHub-Event": "pull_request"},
    )
    assert "summarize-pr" in prompt
    assert "pull_request" in prompt
    assert '"action": "opened"' in prompt
    assert '"number": 42' in prompt


def test_build_prompt_skill_binding_with_empty_headers() -> None:
    sub = WebhookSubscription(skill_name="echo", auth_secret="x")
    prompt = _build_prompt(sub, payload={"a": 1}, headers={})
    assert "echo" in prompt
    assert '"a": 1' in prompt


def test_build_prompt_prompt_template_substitutes_payload() -> None:
    sub = WebhookSubscription(
        binding_type="prompt",
        prompt_template="Process this event: {{ payload }}",
        auth_secret="x",
    )
    prompt = _build_prompt(sub, payload={"event": "push"}, headers={})
    assert "Process this event:" in prompt
    assert '"event": "push"' in prompt


def test_build_prompt_template_substitutes_headers() -> None:
    sub = WebhookSubscription(
        binding_type="prompt",
        prompt_template="Event: {{ headers }} / data: {{ payload }}",
        auth_secret="x",
    )
    prompt = _build_prompt(
        sub,
        payload={"x": 1},
        headers={"X-GitHub-Event": "push"},
    )
    assert '"X-GitHub-Event"' in prompt
    assert '"x": 1' in prompt


def test_substitute_template_tolerates_whitespace_variants() -> None:
    """Both {{ payload }} and {{payload}} should work."""
    out = _substitute_template(
        "a {{payload}} b {{ payload }} c {{  payload  }} d",
        payload={"v": 1},
        headers={},
    )
    # All three forms got replaced.
    assert "{{payload}}" not in out
    assert "{{ payload }}" not in out
    assert "{{  payload  }}" not in out


def test_build_prompt_skill_binding_missing_name_raises() -> None:
    """Constructed via __new__ to bypass dataclass __post_init__ —
    catches a corrupted-row case at dispatch time."""
    sub = WebhookSubscription.__new__(WebhookSubscription)
    sub.id = "x"
    sub.binding_type = "skill"
    sub.skill_name = None
    sub.prompt_template = None
    with pytest.raises(ValueError, match="skill_name"):
        _build_prompt(sub, {}, {})


def test_build_prompt_unknown_binding_raises() -> None:
    sub = WebhookSubscription.__new__(WebhookSubscription)
    sub.id = "x"
    sub.binding_type = "telepathy"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="unknown binding_type"):
        _build_prompt(sub, {}, {})


# ---- _parse_gateway_target -----------------------------------------


def test_parse_gateway_well_formed() -> None:
    assert _parse_gateway_target("gateway://telegram/12345") == ("telegram", "12345")


def test_parse_gateway_missing_chat_id() -> None:
    assert _parse_gateway_target("gateway://slack/") is None


def test_parse_gateway_missing_platform() -> None:
    assert _parse_gateway_target("gateway:///chat") is None


def test_parse_gateway_wrong_prefix() -> None:
    assert _parse_gateway_target("https://slack/chat") is None


# ---- dispatch_webhook end-to-end (no daemon) ----------------------


async def test_dispatch_skill_binding_runs_agent_and_logs_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sub = WebhookSubscription(
        skill_name="echo",
        auth_secret="s",
        delivery_target="log",
    )
    agent = _StubAgent(response="agent says hi")
    with caplog.at_level(logging.INFO, logger="athena.webhooks.delivery"):
        await dispatch_webhook(
            daemon=None,
            sub=sub,
            payload={"action": "opened"},
            headers={"X-GitHub-Event": "issue"},
            agent_factory=lambda: agent,
        )
    assert agent.run_calls, "agent.run_until_done should have been called"
    prompt = agent.run_calls[0]
    assert "echo" in prompt
    assert '"action": "opened"' in prompt
    assert agent.closed is True
    # Response landed in the log.
    assert any("agent says hi" in r.message for r in caplog.records)


async def test_dispatch_prompt_template_substitutes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sub = WebhookSubscription(
        binding_type="prompt",
        prompt_template="Summarize: {{ payload }}",
        auth_secret="s",
        delivery_target="log",
    )
    agent = _StubAgent()
    await dispatch_webhook(
        daemon=None,
        sub=sub,
        payload={"title": "fix bug"},
        headers={},
        agent_factory=lambda: agent,
    )
    assert "Summarize:" in agent.run_calls[0]
    assert '"title": "fix bug"' in agent.run_calls[0]


async def test_dispatch_file_delivery_appends(tmp_path: Path) -> None:
    output = tmp_path / "webhook-log.txt"
    sub = WebhookSubscription(
        skill_name="echo",
        auth_secret="s",
        delivery_target=f"file:{output}",
    )
    agent = _StubAgent(response="first response")
    await dispatch_webhook(
        daemon=None,
        sub=sub,
        payload={},
        headers={},
        agent_factory=lambda: agent,
    )
    body = output.read_text(encoding="utf-8")
    assert "first response" in body
    assert "--- webhook" in body  # delimiter

    # Second dispatch appends, doesn't truncate.
    agent2 = _StubAgent(response="second response")
    await dispatch_webhook(
        daemon=None,
        sub=sub,
        payload={},
        headers={},
        agent_factory=lambda: agent2,
    )
    body2 = output.read_text(encoding="utf-8")
    assert "first response" in body2
    assert "second response" in body2


async def test_dispatch_none_delivery_discards_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sub = WebhookSubscription(
        skill_name="echo",
        auth_secret="s",
        delivery_target="none",
    )
    agent = _StubAgent(response="nobody sees this")
    with caplog.at_level(logging.INFO, logger="athena.webhooks.delivery"):
        await dispatch_webhook(
            daemon=None,
            sub=sub,
            payload={},
            headers={},
            agent_factory=lambda: agent,
        )
    # Agent ran but nothing logged the response.
    assert agent.run_calls
    assert not any("nobody sees this" in r.message for r in caplog.records)


async def test_dispatch_unknown_target_falls_back_to_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sub = WebhookSubscription(
        skill_name="echo",
        auth_secret="s",
        delivery_target="unknown://schema",
    )
    agent = _StubAgent(response="response text")
    with caplog.at_level(logging.WARNING, logger="athena.webhooks.delivery"):
        await dispatch_webhook(
            daemon=None,
            sub=sub,
            payload={},
            headers={},
            agent_factory=lambda: agent,
        )
    msgs = " ".join(r.message for r in caplog.records)
    assert "unknown delivery_target" in msgs


# ---- gateway delivery ---------------------------------------------


async def test_dispatch_gateway_delivery_routes_through_adapter() -> None:
    sub = WebhookSubscription(
        skill_name="echo",
        auth_secret="s",
        delivery_target="gateway://telegram/12345",
    )
    agent = _StubAgent(response="webhook response")

    send_text = AsyncMock()
    adapter = SimpleNamespace(name="telegram", send_text=send_text)
    daemon = SimpleNamespace(adapter_for=lambda p: adapter)

    await dispatch_webhook(
        daemon=daemon,
        sub=sub,
        payload={"x": 1},
        headers={},
        agent_factory=lambda: agent,
    )

    send_text.assert_awaited_once_with("12345", "webhook response")


async def test_dispatch_gateway_no_adapter_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sub = WebhookSubscription(
        skill_name="echo",
        auth_secret="s",
        delivery_target="gateway://discord/1234567890",
    )
    daemon = SimpleNamespace(adapter_for=lambda p: None)
    with caplog.at_level(logging.WARNING, logger="athena.webhooks.delivery"):
        await dispatch_webhook(
            daemon=daemon,
            sub=sub,
            payload={},
            headers={},
            agent_factory=lambda: _StubAgent(),
        )
    msgs = " ".join(r.message for r in caplog.records)
    assert "no 'discord' adapter" in msgs


async def test_dispatch_gateway_no_daemon_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Webhook configured with gateway:// but daemon missing — log
    a clear hint and don't crash."""
    sub = WebhookSubscription(
        skill_name="echo",
        auth_secret="s",
        delivery_target="gateway://telegram/12345",
    )
    with caplog.at_level(logging.WARNING, logger="athena.webhooks.delivery"):
        await dispatch_webhook(
            daemon=None,
            sub=sub,
            payload={},
            headers={},
            agent_factory=lambda: _StubAgent(),
        )
    msgs = " ".join(r.message for r in caplog.records)
    assert "no daemon" in msgs


async def test_dispatch_gateway_malformed_target_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sub = WebhookSubscription(
        skill_name="echo",
        auth_secret="s",
        delivery_target="gateway://busted",
    )
    daemon = SimpleNamespace(adapter_for=lambda p: None)
    with caplog.at_level(logging.WARNING, logger="athena.webhooks.delivery"):
        await dispatch_webhook(
            daemon=daemon,
            sub=sub,
            payload={},
            headers={},
            agent_factory=lambda: _StubAgent(),
        )
    msgs = " ".join(r.message for r in caplog.records)
    assert "malformed gateway target" in msgs


async def test_dispatch_gateway_send_failure_logged_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Adapter send_text exception must not propagate."""
    sub = WebhookSubscription(
        skill_name="echo",
        auth_secret="s",
        delivery_target="gateway://telegram/1",
    )
    send_text = AsyncMock(side_effect=RuntimeError("API rate limit"))
    adapter = SimpleNamespace(name="telegram", send_text=send_text)
    daemon = SimpleNamespace(adapter_for=lambda p: adapter)

    with caplog.at_level(logging.ERROR, logger="athena.webhooks.delivery"):
        # Must not raise.
        await dispatch_webhook(
            daemon=daemon,
            sub=sub,
            payload={},
            headers={},
            agent_factory=lambda: _StubAgent(),
        )
    msgs = " ".join(r.message for r in caplog.records)
    assert "gateway send" in msgs


# ---- agent failure paths -----------------------------------------


async def test_dispatch_agent_construction_failure_logged_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sub = WebhookSubscription(
        skill_name="echo",
        auth_secret="s",
        delivery_target="log",
    )

    def broken_factory():
        raise RuntimeError("provider init failed")

    with caplog.at_level(logging.ERROR, logger="athena.webhooks.delivery"):
        await dispatch_webhook(
            daemon=None,
            sub=sub,
            payload={},
            headers={},
            agent_factory=broken_factory,
        )
    msgs = " ".join(r.message for r in caplog.records)
    assert "agent run failed" in msgs


async def test_dispatch_agent_run_exception_logged_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _CrashAgent(_StubAgent):
        def run_until_done(self, *_a, **_kw) -> None:
            raise RuntimeError("simulated crash")

    sub = WebhookSubscription(
        skill_name="echo",
        auth_secret="s",
        delivery_target="log",
    )
    with caplog.at_level(logging.ERROR, logger="athena.webhooks.delivery"):
        await dispatch_webhook(
            daemon=None,
            sub=sub,
            payload={},
            headers={},
            agent_factory=lambda: _CrashAgent(),
        )
    msgs = " ".join(r.message for r in caplog.records)
    assert "agent run failed" in msgs


async def test_dispatch_empty_response_still_logs() -> None:
    """Agent returns empty string → log path triggers with '(empty)'."""
    sub = WebhookSubscription(
        skill_name="echo",
        auth_secret="s",
        delivery_target="log",
    )
    agent = _StubAgent(response="")
    # Just verify no exception.
    await dispatch_webhook(
        daemon=None,
        sub=sub,
        payload={},
        headers={},
        agent_factory=lambda: agent,
    )
