"""0.3.0 hardening -- per-user / per-channel inbound allowlists.

Pins :meth:`GatewayAdapter.handle_inbound`'s refuse-by-allowlist
guard. Goals:

  * Empty allowlists -> open posture (back-compat). Pre-0.3.0
    deployments with no [gateway.platforms.<name>] config carry on
    as before.
  * Populated ``allowed_user_ids`` -> only those users routed. Every
    other event drops silently with an INFO log entry; nothing
    downstream (router, agent pool, tool dispatch) sees it.
  * Populated ``allowed_chat_ids`` -> same semantics, keyed on
    ``chat_id``.
  * Both populated -> intersection. A user whose id is allowed but
    who messages from a chat that isn't allowed is still refused
    (covers the "right person, wrong server" case in Discord).
  * Non-string id types (Discord delivers ints) coerce via str().
  * Malformed config (allowed_user_ids = "foo" instead of a list)
    fails open with an empty allowlist -- never blocks the operator
    out of their own bot due to a TOML typo.

The check runs BEFORE ``daemon.router.resolve`` so even the act of
mapping a refused message to a session is skipped -- nothing leaks
into the audit log surface beyond the rejection itself.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from athena.gateway.base import GatewayAdapter
from athena.gateway.events import MessageEvent

# ---------------------------------------------------------------------------
# Test doubles -- minimal daemon + adapter, just enough for the guard
# ---------------------------------------------------------------------------


class _FakeRouter:
    def __init__(self) -> None:
        self.calls: list[MessageEvent] = []

    async def resolve(self, event: MessageEvent) -> str:
        self.calls.append(event)
        return "sess-1"


def _daemon(*, platform_cfg: dict[str, Any] | None = None) -> SimpleNamespace:
    """Compose just enough Config-shaped state for the new helpers.

    daemon.cfg.gateway.platforms is the slice the adapter reads. The
    real Config object is a frozen dataclass tree; SimpleNamespace
    matches the attribute reads ``_platform_config`` does
    (`getattr(cfg, 'gateway')` -> `getattr(gateway, 'platforms')`).
    """
    gateway = SimpleNamespace(
        platforms={"test": platform_cfg} if platform_cfg is not None else {},
    )
    cfg = SimpleNamespace(gateway=gateway)
    return SimpleNamespace(
        cfg=cfg,
        router=_FakeRouter(),
        dispatch_command=AsyncMock(return_value="ok"),
    )


class _TestAdapter(GatewayAdapter):
    name = "test"

    def __init__(self, daemon: Any) -> None:
        super().__init__(daemon)
        self.sent_text: list[tuple[str, str]] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_text(self, chat_id: str, text: str) -> str:
        self.sent_text.append((chat_id, text))
        return "msg-id"

    async def send_file(self, chat_id: str, file_path: Path, caption: str | None = None) -> str:
        return "msg-id"


def _evt(
    user_id: str = "user-1",
    chat_id: str = "chat-1",
    text: str = "hi",
) -> MessageEvent:
    return MessageEvent(
        platform="test",
        chat_id=chat_id,
        user_id=user_id,
        text=text,
    )


# ---------------------------------------------------------------------------
# Empty allowlists keep the pre-0.3.0 open posture
# ---------------------------------------------------------------------------


async def test_no_platform_config_authorizes_anyone() -> None:
    """No ``[gateway.platforms.test]`` block at all -> open posture."""
    adapter = _TestAdapter(_daemon())
    assert adapter._is_authorized(_evt(user_id="anyone", chat_id="anywhere")) is True


async def test_empty_allowlists_authorize_anyone() -> None:
    """Config present but both lists empty -> still open. Operators
    who want to declare a platform without locking it down (e.g. to
    set ``poll_interval_s``) shouldn't be auto-locked."""
    adapter = _TestAdapter(_daemon(platform_cfg={"allowed_user_ids": [], "allowed_chat_ids": []}))
    assert adapter._is_authorized(_evt()) is True


async def test_malformed_allowlist_falls_back_to_open() -> None:
    """``allowed_user_ids = "alice"`` (TOML typo for a list) MUST NOT
    silently lock everyone out -- coerce to an empty set and stay
    open. The alternative -- refusing to start the bot -- gates the
    operator out of their own daemon."""
    adapter = _TestAdapter(_daemon(platform_cfg={"allowed_user_ids": "alice"}))
    assert adapter._is_authorized(_evt(user_id="alice")) is True


# ---------------------------------------------------------------------------
# Populated allowlists enforce the operator's intent
# ---------------------------------------------------------------------------


async def test_user_allowlist_admits_listed_user() -> None:
    adapter = _TestAdapter(_daemon(platform_cfg={"allowed_user_ids": ["alice", "bob"]}))
    assert adapter._is_authorized(_evt(user_id="alice")) is True
    assert adapter._is_authorized(_evt(user_id="bob")) is True


async def test_user_allowlist_refuses_unlisted_user() -> None:
    adapter = _TestAdapter(_daemon(platform_cfg={"allowed_user_ids": ["alice"]}))
    assert adapter._is_authorized(_evt(user_id="mallory")) is False


async def test_chat_allowlist_refuses_unlisted_chat() -> None:
    adapter = _TestAdapter(_daemon(platform_cfg={"allowed_chat_ids": ["chat-trusted"]}))
    assert adapter._is_authorized(_evt(user_id="alice", chat_id="chat-public")) is False


async def test_both_allowlists_require_both_to_match() -> None:
    """Discord case: alice is allowed AS A USER, but only when she
    posts in the right channel. A message from alice in a public
    channel that isn't on the list MUST still be refused."""
    adapter = _TestAdapter(
        _daemon(
            platform_cfg={
                "allowed_user_ids": ["alice"],
                "allowed_chat_ids": ["chat-trusted"],
            }
        )
    )
    assert adapter._is_authorized(_evt(user_id="alice", chat_id="chat-trusted")) is True
    assert adapter._is_authorized(_evt(user_id="alice", chat_id="chat-public")) is False
    assert adapter._is_authorized(_evt(user_id="mallory", chat_id="chat-trusted")) is False


async def test_numeric_ids_coerce_to_strings() -> None:
    """Discord delivers user/channel ids as integers. The config TOML
    might list them as either ints or strings. The adapter normalises
    both sides to str() so a config of ``[123456]`` matches an event
    with ``user_id=123456`` or ``user_id="123456"``."""
    adapter = _TestAdapter(_daemon(platform_cfg={"allowed_user_ids": [123_456]}))
    assert adapter._is_authorized(_evt(user_id="123456")) is True
    assert adapter._is_authorized(_evt(user_id=123_456)) is True  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# handle_inbound integration -- refused events skip the router entirely
# ---------------------------------------------------------------------------


async def test_refused_event_never_reaches_router(caplog) -> None:
    """A rejected message must not be resolved to a session, must not
    spawn a processing task, must not be saved as pending. The
    operator's audit trail records the refusal; nothing else."""
    daemon = _daemon(platform_cfg={"allowed_user_ids": ["alice"]})
    adapter = _TestAdapter(daemon)
    # If the router or the processing path ever fires, that's a bug.
    spawn = AsyncMock(side_effect=AssertionError("router reached"))
    adapter._process_message_background = spawn  # type: ignore[assignment]

    with caplog.at_level(logging.INFO, logger="athena.gateway.base"):
        await adapter.handle_inbound(_evt(user_id="mallory", chat_id="chat-1"))
    # Yield once so any erroneously-spawned task would surface.
    await asyncio.sleep(0)

    assert daemon.router.calls == [], "router should not see refused events"
    assert "sess-1" not in adapter._active_sessions
    assert not adapter._pending_messages
    spawn.assert_not_called()
    # Refusal logged at INFO so an operator can grep it.
    rejected_lines = [rec for rec in caplog.records if "rejected inbound message" in rec.message]
    assert rejected_lines, "expected INFO log entry for the refusal"


async def test_authorized_event_still_reaches_router() -> None:
    """The reverse pin: when authorization passes, handle_inbound
    proceeds normally to the router."""
    daemon = _daemon(platform_cfg={"allowed_user_ids": ["alice"]})
    adapter = _TestAdapter(daemon)
    spawn = AsyncMock()
    adapter._process_message_background = spawn  # type: ignore[assignment]

    await adapter.handle_inbound(_evt(user_id="alice", chat_id="chat-1"))
    await asyncio.sleep(0)

    assert len(daemon.router.calls) == 1
    spawn.assert_awaited_once()
