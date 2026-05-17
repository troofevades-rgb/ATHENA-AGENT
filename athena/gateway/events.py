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

The ``message_type`` field discriminates text / media events and is
what the base adapter's busy-session policy keys off: rapid text
follow-ups *interrupt* the in-flight turn (merged into a single pending
slot), while photo bursts *queue without interrupting* so an album
doesn't keep restarting the agent. Hermes Agent encodes the same rule;
the field exists so the policy is uniform across adapters.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MessageType(str, enum.Enum):
    """Inbound message kind.

    ``TEXT`` and ``PHOTO`` are the two shapes the base adapter has
    distinct busy-session policies for. ``AUDIO``, ``VIDEO``,
    ``DOCUMENT``, ``STICKER``, and ``OTHER`` are recognized for
    completeness — adapters set them from the native payload and the
    base adapter treats them the same as TEXT until a future phase
    needs to special-case them.
    """

    TEXT = "text"
    PHOTO = "photo"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"
    OTHER = "other"


@dataclass
class MessageEvent:
    """A single inbound message normalized across platforms.

    ``platform`` is the adapter's :attr:`~GatewayAdapter.name`
    (``"telegram"``, ``"slack"``, ``"discord"``, ...). ``chat_id`` and
    ``user_id`` are the platform's IDs as strings — coerce non-string
    IDs (Telegram's int chat ids) before constructing the event.

    ``attachments`` carries local cached paths the adapter has already
    written to disk for media events — the tool layer reads from there,
    not from any platform-specific URL. ``raw`` carries the
    platform-native payload for adapter-specific handling.
    """

    platform: str
    chat_id: str
    user_id: str
    text: str
    message_type: MessageType = MessageType.TEXT
    attachments: list[Path] = field(default_factory=list)
    is_dm: bool = True
    reply_to_message_id: str | None = None
    platform_message_id: str = ""
    received_at: datetime = field(default_factory=_utcnow)
    raw: dict[str, Any] = field(default_factory=dict)

    def is_command(self) -> bool:
        """True if ``text`` begins with ``/`` — used by the base
        adapter to route bypass commands (``/stop``, ``/new``, ...)
        around the busy-session guard."""
        return self.text.startswith("/")

    def get_command(self) -> str | None:
        """Return the command name (without the leading ``/``) or None.

        Strips a Telegram-style ``@botname`` suffix. Rejects strings
        that look like file paths (a command never contains ``/``
        after the leading slash).
        """
        if not self.is_command():
            return None
        head = self.text.split(maxsplit=1)[0]
        raw = head[1:].lower()
        if "@" in raw:
            raw = raw.split("@", 1)[0]
        if "/" in raw:
            return None
        return raw or None


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
