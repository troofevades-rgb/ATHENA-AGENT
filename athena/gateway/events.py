"""Platform-neutral inbound and approval event records.

:class:`MessageEvent` is what every :class:`~athena.gateway.base.GatewayAdapter`
constructs from a platform-native payload before dispatching it into the
daemon. Keeping the shape platform-neutral is how the rest of the
gateway stays free of platform-specific code.

:class:`ApprovalRequest` is the in-flight record the daemon hands an
adapter when a dangerous tool wants user confirmation. The adapter
renders it via its platform's UI (Telegram inline buttons, Slack block
kit, Discord ``ui.View``) and reports the decision back through the
approval router.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class MessageEvent:
    """A single inbound message normalized across platforms.

    ``platform`` is the adapter's :attr:`~GatewayAdapter.name`
    (``"telegram"``, ``"slack"``, ``"discord"``, ...). ``chat_id`` and
    ``user_id`` are the platform's IDs as strings — coerce non-string
    IDs (Telegram's int chat ids) before constructing the event.

    ``raw`` carries the platform-native payload for any adapter-specific
    handling that the neutral fields don't cover. Nothing in the core
    daemon reads it; it's a hook for adapter code.
    """

    platform: str
    chat_id: str
    user_id: str
    text: str
    attachments: list[Path] = field(default_factory=list)
    is_dm: bool = True
    reply_to_message_id: str | None = None
    platform_message_id: str = ""
    received_at: datetime = field(default_factory=_utcnow)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalRequest:
    """Pending user-approval record for a dangerous tool call.

    Created by the approval router when a tool requests confirmation,
    handed to the adapter for rendering, and resolved (with
    ``decision``/``answered_at`` set) when the user clicks allow/deny —
    or when the router times the request out.
    """

    session_id: str
    tool_name: str
    tool_args: dict[str, Any]
    request_id: str
    asked_at: datetime = field(default_factory=_utcnow)
    answered_at: datetime | None = None
    decision: Literal["allow", "deny"] | None = None
