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
    """Default: interactive prompt via ``ui.confirm`` with a tool-
    appropriate preview so the user sees WHAT is about to run, not
    just the tool name. Bash gets the command; Edit/Write get a
    file path + content/diff; other tools get a JSON arg dump."""
    from .. import ui  # local import — avoids circular at module load

    preview, kind = _build_preview(tool_name, args)
    return "allow" if ui.confirm(
        f"Run {tool_name}?", default=False,
        tool_name=tool_name, preview=preview, preview_kind=kind,
    ) else "deny"


def _build_preview(tool_name: str, args: dict) -> tuple[str | None, str | None]:
    """Build a human-readable preview of what ``tool_name(args)`` is
    about to do. Returns ``(preview, kind)`` where ``kind`` is one
    of ``"command"``, ``"diff"``, ``"file"``, ``"text"``, or None.

    Best-effort; never raises. Falls back to a short args dump so
    the user always sees SOMETHING beyond the tool name.
    """
    try:
        name = (tool_name or "").lower()
        if name in ("bash", "shell", "run_shell_command"):
            cmd = args.get("command") or args.get("cmd") or ""
            if cmd:
                return (str(cmd), "command")
        if name in ("write", "write_file"):
            path = args.get("file_path") or args.get("path") or "<unknown>"
            content = args.get("content") or args.get("text") or ""
            preview_body = _truncate_block(content, max_lines=15)
            return (f"{path}\n\n{preview_body}", "file")
        if name in ("edit", "edit_file"):
            path = args.get("file_path") or args.get("path") or "<unknown>"
            old = args.get("old_string") or ""
            new = args.get("new_string") or ""
            return (
                f"--- a/{path}\n+++ b/{path}\n"
                + _format_replace_as_diff(old, new),
                "diff",
            )
        # Fallback: short pretty JSON of args
        import json
        try:
            body = json.dumps(args, indent=2, default=str)[:1000]
        except (TypeError, ValueError):
            body = repr(args)[:1000]
        return (body, "text")
    except Exception:  # noqa: BLE001 — preview is best-effort
        return (None, None)


def _truncate_block(text: str, *, max_lines: int = 15) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    head = "\n".join(lines[:max_lines])
    return f"{head}\n… ({len(lines) - max_lines} more lines)"


def _format_replace_as_diff(old: str, new: str) -> str:
    """Tiny diff renderer for the Edit tool's old→new swap. We
    don't call difflib here because the Edit tool's old_string is
    typically a SLICE of the file, not the whole file — a real
    unified diff would need line numbers from disk. Showing the
    two blocks as -/+ is honest about what's changing."""
    out: list[str] = []
    for line in old.splitlines() or [""]:
        out.append(f"-{line}")
    for line in new.splitlines() or [""]:
        out.append(f"+{line}")
    return "\n".join(out)


def AUTO_DENY(tool_name: str, args: dict) -> str:
    """Refuse every confirmation prompt without user input.

    Used by forks. The denial is logged at WARNING so background forks that
    repeatedly try to escalate are visible in observability.
    """
    logger.warning("fork auto-denied confirmation prompt: tool=%s args=%s", tool_name, args)
    return "deny"


_approval: contextvars.ContextVar[ApprovalFn] = contextvars.ContextVar(
    "athena_approval_callback", default=_interactive_approval
)


def set_approval_callback(fn: ApprovalFn) -> contextvars.Token[ApprovalFn]:
    """Bind the active approval callback. Returns a token for ``reset_approval_callback``."""
    return _approval.set(fn)


def reset_approval_callback(token: contextvars.Token[ApprovalFn]) -> None:
    _approval.reset(token)


def get_approval_callback() -> ApprovalFn:
    """Return the approval callback bound to the current context."""
    return _approval.get()
