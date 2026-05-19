"""Per-thread approval callback for tool calls that require confirmation.

The default callback prompts the user interactively via ``ui.confirm``. Forks
install :data:`AUTO_DENY` at thread entry so a background fork cannot deadlock
on a confirmation it has no way to satisfy. Plug-in replacements (e.g. the
gateway adapter in Phase 10) can route prompts to chat platforms.
"""

import contextvars
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

ApprovalFn = Callable[[str, dict], str]
"""(tool_name, args) -> "allow" | "deny"."""


def _interactive_approval(tool_name: str, args: dict) -> str:
    """Default: interactive prompt via ``ui.confirm``."""
    from .. import ui  # local import — avoids circular at module load

    return "allow" if ui.confirm(f"Run {tool_name}?", default=False) else "deny"


def AUTO_DENY(tool_name: str, args: dict) -> str:
    """Refuse every confirmation prompt without user input.

    Used by forks. The denial is logged at WARNING so background forks that
    repeatedly try to escalate are visible in observability.
    """
    logger.warning("fork auto-denied confirmation prompt: tool=%s args=%s", tool_name, args)
    return "deny"


_approval: contextvars.ContextVar[ApprovalFn] = contextvars.ContextVar(
    "ocode_approval_callback", default=_interactive_approval
)


def set_approval_callback(fn: ApprovalFn) -> contextvars.Token[ApprovalFn]:
    """Bind the active approval callback. Returns a token for ``reset_approval_callback``."""
    return _approval.set(fn)


def reset_approval_callback(token: contextvars.Token[ApprovalFn]) -> None:
    _approval.reset(token)


def get_approval_callback() -> ApprovalFn:
    """Return the approval callback bound to the current context."""
    return _approval.get()
