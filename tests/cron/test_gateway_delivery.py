"""cron→gateway delivery — Phase 10.7 wiring of the
``gateway://<platform>/<chat_id>`` cron delivery target."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from athena.cron import delivery


def _job(target: str, job_id: str = "job-1", profile: str = "default"):
    return SimpleNamespace(
        id=job_id,
        description="test description",
        delivery_target=target,
        profile=profile,
    )


def setup_function(_func) -> None:
    from athena.gateway import registry
    registry._clear_for_tests()


# ---- target parsing ---------------------------------------------------


def test_parse_gateway_target_well_formed() -> None:
    assert delivery._parse_gateway_target(
        "gateway://telegram/12345"
    ) == ("telegram", "12345")


def test_parse_gateway_target_with_complex_chat_id() -> None:
    """Slack channel IDs contain letters; Discord ids are huge ints —
    parser must not over-validate."""
    assert delivery._parse_gateway_target(
        "gateway://discord/123456789012345678"
    ) == ("discord", "123456789012345678")


def test_parse_gateway_target_missing_chat_id() -> None:
    assert delivery._parse_gateway_target("gateway://telegram/") is None


def test_parse_gateway_target_missing_platform() -> None:
    assert delivery._parse_gateway_target("gateway:///12345") is None


def test_parse_gateway_target_wrong_prefix() -> None:
    assert delivery._parse_gateway_target("https://telegram/x") is None


def test_parse_gateway_target_no_separator() -> None:
    assert delivery._parse_gateway_target("gateway://telegramfoo") is None


# ---- delivery falls back to log when prerequisites missing ------------


def test_gateway_delivery_falls_back_when_no_daemon(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No gateway running for the profile → warn and log instead."""
    job = _job("gateway://telegram/123")
    with caplog.at_level(logging.WARNING, logger="athena.cron"):
        delivery.deliver(job, {"status": "ok", "output": "done"})
    msgs = " ".join(r.message for r in caplog.records)
    assert "no running gateway" in msgs


def test_gateway_delivery_falls_back_when_malformed_target(
    caplog: pytest.LogCaptureFixture,
) -> None:
    job = _job("gateway://busted")
    with caplog.at_level(logging.WARNING, logger="athena.cron"):
        delivery.deliver(job, {"status": "ok"})
    msgs = " ".join(r.message for r in caplog.records)
    assert "malformed" in msgs


def test_gateway_delivery_falls_back_when_no_adapter_registered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Gateway is up but the named platform isn't registered."""
    from athena.gateway import registry

    fake = SimpleNamespace(
        cfg=SimpleNamespace(profile="default"),
        adapter_for=lambda p: None,
        approvals=SimpleNamespace(_loop=None),
    )
    registry.register(fake)
    try:
        with caplog.at_level(logging.WARNING, logger="athena.cron"):
            delivery.deliver(
                _job("gateway://slack/CX"),
                {"status": "ok"},
            )
        msgs = " ".join(r.message for r in caplog.records)
        assert "no 'slack' adapter" in msgs or "no \"slack\" adapter" in msgs
    finally:
        registry.unregister(fake)


# ---- end-to-end via a running asyncio loop ----------------------------


async def test_gateway_delivery_dispatches_to_adapter() -> None:
    """Register a fake daemon + adapter; verify send_text is called
    with the rendered body."""
    from athena.gateway import registry

    loop = asyncio.get_running_loop()
    send_text = AsyncMock(return_value="msg-1")
    adapter = SimpleNamespace(name="telegram", send_text=send_text)
    fake_daemon = SimpleNamespace(
        cfg=SimpleNamespace(profile="default"),
        adapters=[adapter],
        adapter_for=lambda p: adapter if p == "telegram" else None,
        approvals=SimpleNamespace(_loop=loop),
    )
    registry.register(fake_daemon)
    try:
        import functools

        # delivery.deliver is sync — execute it on a thread so the
        # run_coroutine_threadsafe inside doesn't deadlock.
        await asyncio.to_thread(
            functools.partial(
                delivery.deliver,
                _job("gateway://telegram/12345", profile="default"),
                {"status": "ok", "output": "hello world"},
            )
        )
    finally:
        registry.unregister(fake_daemon)

    send_text.assert_awaited_once()
    args, _ = send_text.await_args
    assert args[0] == "12345"
    body = args[1]
    assert "test description" in body
    assert "hello world" in body
    assert "ok" in body


async def test_gateway_delivery_long_output_truncated() -> None:
    from athena.gateway import registry

    loop = asyncio.get_running_loop()
    send_text = AsyncMock(return_value="m")
    adapter = SimpleNamespace(name="telegram", send_text=send_text)
    registry.register(SimpleNamespace(
        cfg=SimpleNamespace(profile="default"),
        adapters=[adapter],
        adapter_for=lambda p: adapter,
        approvals=SimpleNamespace(_loop=loop),
    ))
    try:
        import functools
        await asyncio.to_thread(
            functools.partial(
                delivery.deliver,
                _job("gateway://telegram/1"),
                {"status": "ok", "output": "x" * 5000},
            )
        )
    finally:
        from athena.gateway import registry
        registry._clear_for_tests()

    body = send_text.await_args.args[1]
    assert "…" in body
    assert len(body) < 2500


async def test_gateway_delivery_handles_send_text_failure() -> None:
    """A send-text failure must fall through to log delivery rather
    than propagate (cron's deliver() also catches but the inner code
    should already self-recover)."""
    from athena.gateway import registry

    loop = asyncio.get_running_loop()
    send_text = AsyncMock(side_effect=RuntimeError("api down"))
    adapter = SimpleNamespace(name="telegram", send_text=send_text)
    registry.register(SimpleNamespace(
        cfg=SimpleNamespace(profile="default"),
        adapters=[adapter],
        adapter_for=lambda p: adapter,
        approvals=SimpleNamespace(_loop=loop),
    ))
    try:
        import functools
        # Must not raise.
        await asyncio.to_thread(
            functools.partial(
                delivery.deliver,
                _job("gateway://telegram/1"),
                {"status": "ok"},
            )
        )
    finally:
        from athena.gateway import registry
        registry._clear_for_tests()
