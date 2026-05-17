"""Text-reply approval support for platforms without native buttons.

Signal / iMessage / Email don't have inline-button UI the way
Telegram / Slack / Discord do. They fall back to a text prompt
("Approve `Bash`? Reply with /allow or /deny.") and intercept the
user's next message.

Each adapter mixes :class:`TextApprovalState` in to track the
``(user_id) → request_id`` mapping and call
:func:`parse_approval_decision` on inbound text before it reaches
:meth:`handle_inbound`.

Why keyed on user_id: Signal/iMessage/Email all carry a stable
per-user identifier with every inbound message. Storing the pending
request id against that identifier means an unrelated chat member
typing ``/allow`` can't accidentally resolve someone else's
approval.
"""
from __future__ import annotations

import logging
from typing import Literal

from ..events import ApprovalRequest

logger = logging.getLogger(__name__)


Decision = Literal["allow", "deny"]


_ALLOW_TOKENS = frozenset({"/allow", "allow", "✅", "yes", "y", "ok"})
_DENY_TOKENS = frozenset({"/deny", "deny", "✖", "no", "n", "stop"})


def parse_approval_decision(text: str) -> Decision | None:
    """Return ``"allow"`` / ``"deny"`` if ``text`` is a single-token
    approval reply. Returns ``None`` otherwise — the message goes
    through normal turn handling.

    Matching is case-insensitive and strips surrounding whitespace.
    Multi-word inputs ("yes please run it") deliberately do NOT
    match — too ambiguous, and the user typed enough to suggest they
    didn't realize the prompt was a binary choice. Surface those
    as a regular turn so the agent can clarify.
    """
    if not text:
        return None
    token = text.strip().lower()
    if not token or " " in token:
        return None
    if token in _ALLOW_TOKENS:
        return "allow"
    if token in _DENY_TOKENS:
        return "deny"
    return None


class TextApprovalState:
    """Mixin-style helper. Mix in alongside :class:`GatewayAdapter`
    (multiple inheritance) and call :meth:`__init__` from your
    adapter's ``__init__`` after ``super().__init__(daemon)``.

    Provides:

    - :meth:`record_pending`: store ``request_id`` against
      ``user_id`` when an approval prompt goes out.
    - :meth:`try_resolve_approval`: check inbound text; if it's an
      approval reply for a known pending request, resolve it via
      ``daemon.approvals.resolve`` and return True. Caller then
      skips ``handle_inbound`` for this message.
    - :meth:`format_text_approval_prompt`: stock prompt body shared
      by every text-reply adapter so the user sees the same wording
      regardless of platform.
    """

    def __init__(self) -> None:
        self._pending_text_approvals: dict[str, str] = {}

    def record_pending(self, user_id: str, request_id: str) -> None:
        if not user_id:
            return
        # Overwrite any prior unresolved pending — the most-recent
        # tool to ask wins. A user who left the previous prompt
        # unanswered for 5 minutes will see the new one show up;
        # the stale one auto-denies on the router's timeout anyway.
        self._pending_text_approvals[user_id] = request_id

    def try_resolve_approval(self, user_id: str, text: str) -> bool:
        if not user_id:
            return False
        request_id = self._pending_text_approvals.get(user_id)
        if request_id is None:
            return False
        decision = parse_approval_decision(text)
        if decision is None:
            return False
        self._pending_text_approvals.pop(user_id, None)
        try:
            self.daemon.approvals.resolve(request_id, decision)  # type: ignore[attr-defined]
        except Exception:
            logger.exception(
                "text-approval resolve raised for %s", request_id,
            )
        return True

    def clear_pending(self, user_id: str) -> None:
        self._pending_text_approvals.pop(user_id, None)

    @staticmethod
    def format_text_approval_prompt(request: ApprovalRequest) -> str:
        """Stock approval body for text-only platforms.

        Includes the tool name and any user-visible arguments,
        truncated so the message stays comfortably under per-platform
        body caps (Signal ~2KB recommended, iMessage ~5KB, Email
        much higher but readability matters).
        """
        head = f"⚠ Approve `{request.tool_name}`?"
        if request.tool_args:
            arg_lines = []
            for key, value in request.tool_args.items():
                repr_value = str(value)
                if len(repr_value) > 200:
                    repr_value = repr_value[:200] + "…"
                arg_lines.append(f"  {key}: {repr_value}")
            arg_block = "\n".join(arg_lines)
            return (
                f"{head}\n\nArguments:\n{arg_block}\n\n"
                "Reply with /allow or /deny."
            )
        return f"{head}\n\nReply with /allow or /deny."
