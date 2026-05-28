"""``clarify`` tool: ask the user a multiple-choice question.

When the agent's request is ambiguous between plausible
interpretations, this tool surfaces a numbered prompt and returns
the user's selection rather than letting the agent guess (and burn
a turn correcting it).

Three resolution paths in priority order:

1. **Background fork** (curator, auxiliary, sub-agent forks):
   AUTO_DENY. The tool returns "no answer received (background
   fork)" immediately, without blocking. ``in_fork_context``
   ContextVar is set to True by ``athena/agent/fork.py:_runner``.

2. **Gateway hook** (Telegram, Discord, Slack — Tier 4): the
   platform owns the interaction. The gateway adapter registers a
   ``GatewayClarifyHook`` via ``register_gateway_hook`` at startup;
   the hook's ``resolve(question, options, timeout_seconds,
   allow_freeform)`` returns the answer or ``None`` to fall through
   to stdin.

3. **Foreground stdin**: numbered prompt; blocking read via a
   daemon thread + Queue so the per-call timeout can fire even if
   the user steps away.

Sync — matches athena's sync tool surface. The gateway hook is also
sync; the gateway adapter wraps its async platform input in a sync
interface.
"""

from __future__ import annotations

import contextvars
import logging
import queue as _queue
import threading

from .. import ui
from .registry import tool

logger = logging.getLogger(__name__)


# ContextVar set by fork.py:_runner before each fork's run_until_done
# call. AUTO_DENY signal: the tool returns immediately without
# blocking on stdin or the gateway hook.
in_fork_context: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "athena_in_fork", default=False
)


class GatewayClarifyHook:
    """Sync resolver registered by gateway adapters (Tier 4).

    Returning a string resolves the clarify call to that answer.
    Returning ``None`` falls through to stdin (e.g. "the gateway is
    installed but this session isn't bound to a chat adapter").

    The hook is expected to honour ``timeout_seconds`` itself — the
    tool doesn't wrap it in another timeout layer because that would
    require a second thread / event loop in the sync call site.
    """

    def resolve(
        self,
        question: str,
        options: list[str],
        timeout_seconds: int,
        allow_freeform: bool,
    ) -> str | None:
        raise NotImplementedError


_gateway_hook: GatewayClarifyHook | None = None


def register_gateway_hook(hook: GatewayClarifyHook) -> None:
    """Called by a gateway adapter at startup to take over clarify
    resolution. Only one hook at a time."""
    global _gateway_hook
    _gateway_hook = hook


def clear_gateway_hook() -> None:
    """Test affordance / shutdown helper."""
    global _gateway_hook
    _gateway_hook = None


@tool(
    name="clarify",
    toolset="interaction",
    description=(
        "Ask the user a multiple-choice question when their request is "
        "ambiguous between two or more plausible interpretations. "
        "Provide 2-4 short options. Use SPARINGLY — only when guessing "
        "wrong would cost more than asking. If allow_freeform is true, "
        "the user may also type a free-form answer alongside the "
        "numbered options."
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask the user.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-4 short option labels.",
                "minItems": 1,
                "maxItems": 8,
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Max seconds to wait for the user. Default 300.",
            },
            "allow_freeform": {
                "type": "boolean",
                "description": ("If true, accept free-form text not matching a numbered option."),
            },
        },
        "required": ["question", "options"],
    },
)
def clarify(
    question: str = "",
    options: list[str] | None = None,
    timeout_seconds: int = 300,
    allow_freeform: bool = False,
) -> str:
    if not options:
        return "ERROR: clarify requires at least one option"

    # 1. Background fork: AUTO_DENY.
    if in_fork_context.get():
        logger.info(
            "clarify in fork context; auto-denying: %r",
            question[:200],
        )
        return "no answer received (background fork)"

    # 2. Gateway hook (Tier 4 platforms — Telegram / Discord / Slack).
    if _gateway_hook is not None:
        try:
            hook_result = _gateway_hook.resolve(
                question, list(options), int(timeout_seconds), bool(allow_freeform)
            )
        except Exception as e:
            logger.warning("clarify gateway hook raised %s; falling through", type(e).__name__)
            hook_result = None
        if hook_result is not None:
            logger.info(
                "clarify via gateway: q=%r -> %r",
                question[:100],
                hook_result[:100],
            )
            return hook_result
        # None -> fall through to stdin.

    # 3. Foreground stdin.
    answer = _prompt_stdin(question, list(options), bool(allow_freeform), int(timeout_seconds))
    logger.info(
        "clarify via stdin: q=%r -> %r",
        question[:100],
        answer[:100],
    )
    return answer


# A previous clarify call whose stdin reader was orphaned on timeout
# holds onto the next keystroke from the user (Python's ``input()`` can
# only be unblocked by EOF or by a line being typed). When a fresh
# clarify call starts and the prior reader is still blocked, the next
# Enter press goes to the orphan -- the user sees "I pressed Enter and
# nothing happened." We refuse to enqueue a second reader while an
# orphan from a prior call is still in flight; the new call returns the
# timeout sentinel immediately instead. The orphan's eventual line
# never reaches the new clarify but at least we don't race for stdin.
_ORPHAN_READER: threading.Thread | None = None
_ORPHAN_LOCK = threading.Lock()


def _prompt_stdin(
    question: str, options: list[str], allow_freeform: bool, timeout_seconds: int
) -> str:
    """Print the prompt and read one line from stdin with a timeout.

    The reader runs on a daemon thread so the queue-based timeout
    can fire even if the user walks away. The thread will keep
    blocking on ``input()`` after the timeout (Python offers no way
    to interrupt a blocking ``input()`` on either Posix or Windows
    without OS-specific hacks); we track the orphan so the next
    ``_prompt_stdin`` call can detect it and refuse to spawn a
    competitor for the next keystroke.
    """
    global _ORPHAN_READER

    with _ORPHAN_LOCK:
        if _ORPHAN_READER is not None and not _ORPHAN_READER.is_alive():
            _ORPHAN_READER = None
        if _ORPHAN_READER is not None:
            return (
                "no answer received (a prior clarify is still blocked on "
                "stdin; press Enter once to clear it, then retry)"
            )

    ui.console.print(f"\n[bold]?[/] {question}")
    for i, option in enumerate(options, start=1):
        ui.console.print(f"  {i}. {option}")
    hint = (
        f"Choose 1-{len(options)} or type a custom answer: "
        if allow_freeform
        else f"Choose 1-{len(options)}: "
    )

    q: _queue.Queue[tuple[str, str]] = _queue.Queue()

    def _reader() -> None:
        try:
            line = input(hint).strip()
            q.put(("ok", line))
        except (EOFError, KeyboardInterrupt) as e:
            q.put(("err", type(e).__name__))

    t = threading.Thread(target=_reader, daemon=True, name="clarify-stdin")
    t.start()
    try:
        kind, value = q.get(timeout=timeout_seconds)
    except _queue.Empty:
        # Track the orphan so the NEXT clarify call refuses to
        # spawn a competitor for the next keystroke. We don't try
        # to kill the thread -- there's no portable way to interrupt
        # blocking ``input()``.
        with _ORPHAN_LOCK:
            _ORPHAN_READER = t
        return f"no answer received (timeout after {timeout_seconds}s)"

    if kind == "err":
        return f"no answer received ({value})"

    return _resolve_line(value, options, allow_freeform)


def _resolve_line(line: str, options: list[str], allow_freeform: bool) -> str:
    """Map a raw stdin line to one of the options (or freeform).

    Resolution priority:
      1. Pure digit in 1..len(options) -> options[n-1].
      2. Case-insensitive exact label match -> that option.
      3. Case-insensitive prefix match (non-empty input) -> that option.
      4. allow_freeform=True -> return line verbatim.
      5. Fallthrough -> return line verbatim (the agent decides).
    """
    if line.isdigit():
        n = int(line)
        if 1 <= n <= len(options):
            return options[n - 1]

    line_lower = line.lower()
    for option in options:
        if option.lower() == line_lower:
            return option

    if line_lower:
        prefix_matches = [o for o in options if o.lower().startswith(line_lower)]
        if len(prefix_matches) == 1:
            return prefix_matches[0]

    return line
