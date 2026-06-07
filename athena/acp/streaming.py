"""ACP streaming sender — wraps :meth:`ACPServer.send_notification`
with the typed methods :mod:`.methods` calls during a session turn.

Each method maps to one of the ACP notification shapes the client
listens for:

- ``session/content_block_start`` opens a block (text or tool_use).
- ``session/content_block_delta`` carries an incremental update
  (text_delta for streamed tokens).
- ``session/content_block_stop`` closes the current block.
- ``session/tool_result`` carries a tool's output keyed back to the
  open ``tool_use`` block.
- ``session/permission_request`` (request, not notification) asks
  the IDE to render an approval prompt and returns the user's
  decision.

This thin wrapper exists so methods.py doesn't sprinkle string
keys and dict shapes across every code path — adding a new
streaming primitive happens here, once.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .server import ACPServer


_PERMISSION_TIMEOUT = 300.0


class StreamingSender:
    """One sender per active session — closes over the session_id so
    callers don't repeat themselves on every send."""

    def __init__(self, server: ACPServer, session_id: str) -> None:
        self.server = server
        self.session_id = session_id

    # ---- content block lifecycle ----

    async def text_block_start(self, block_id: str = "text-0") -> None:
        await self.server.send_notification(
            "session/content_block_start",
            {
                "session_id": self.session_id,
                "block": {"type": "text", "id": block_id, "text": ""},
            },
        )

    async def text_delta(self, text: str, *, block_id: str = "text-0") -> None:
        """Stream a slice of generated text to the IDE.

        ``block_id`` ties this delta to the open block opened by
        :meth:`text_block_start`. IDEs that don't track blocks can
        ignore the id; the text appends in arrival order anyway.
        """
        if not text:
            return
        await self.server.send_notification(
            "session/content_block_delta",
            {
                "session_id": self.session_id,
                "block_id": block_id,
                "delta": {"type": "text_delta", "text": text},
            },
        )

    async def text_block_stop(self, block_id: str = "text-0") -> None:
        await self.server.send_notification(
            "session/content_block_stop",
            {"session_id": self.session_id, "block_id": block_id},
        )

    # ---- tool calls ----

    async def tool_call_start(
        self,
        tool_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> None:
        await self.server.send_notification(
            "session/content_block_start",
            {
                "session_id": self.session_id,
                "block": {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tool_name,
                    "input": tool_args,
                },
            },
        )

    async def tool_call_result(
        self,
        tool_id: str,
        result: str,
        *,
        is_error: bool = False,
    ) -> None:
        await self.server.send_notification(
            "session/tool_result",
            {
                "session_id": self.session_id,
                "tool_use_id": tool_id,
                "result": result,
                "is_error": is_error,
            },
        )

    # ---- approvals ----

    async def permission_request(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        timeout: float = _PERMISSION_TIMEOUT,
    ) -> Literal["allow", "deny"]:
        """Send a permission_request to the IDE; await the decision.

        Returns ``"deny"`` on any failure (timeout, malformed
        response, IDE error). The safe default for a dangerous tool
        that asked for confirmation.
        """
        try:
            response = await self.server.send_request(
                "session/permission_request",
                {
                    "session_id": self.session_id,
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                },
                timeout=timeout,
            )
        except (asyncio.TimeoutError, Exception):
            return "deny"
        decision = response.get("decision") if isinstance(response, dict) else None
        if decision == "allow":
            return "allow"
        return "deny"

    # ---- session lifecycle hooks ----

    async def turn_started(self) -> None:
        """Emit a marker that a turn is beginning — useful for IDEs
        that want to show a progress indicator."""
        await self.server.send_notification(
            "session/turn_started",
            {"session_id": self.session_id},
        )

    async def turn_completed(self, *, reason: str = "stop") -> None:
        await self.server.send_notification(
            "session/turn_completed",
            {"session_id": self.session_id, "reason": reason},
        )
