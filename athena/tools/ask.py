"""AskUserQuestion tool — pause the agent loop and prompt the user.

Mirrors Claude Code's AskUserQuestion. Models call this when they need a
decision from the user mid-task (rather than guessing). The tool blocks
the agent loop until the user responds.

Each question has 2-4 options; the user can also type free-form text via
the 'Other' option. multiSelect=true lets the user pick multiple.

In TUI mode the tool ships an ``AskQuestionRequestEvent`` to the Ink
gateway and waits on a per-request-id queue for the matching
``AskQuestionReplyCommand``. Calling ``input()`` directly would
deadlock — Ink owns stdin. Without the gateway round-trip the tool
would hang indefinitely (the bug that surfaced in a real session that
sat "still working" for 136 minutes on a question the user never saw).

In headless / non-TUI mode the legacy stdin path is preserved so CLI
scripts and the bare REPL still work.
"""

from __future__ import annotations

import queue as _queue
import uuid as _uuid
from typing import Any

from .. import ui
from .registry import tool


# Per-request reply inbox keyed by request_id. The gateway's
# _dispatch_ask_question_reply pushes into this; the agent thread that
# called AskUserQuestion blocks on .get() for the matching id.
_pending_questions: dict[str, _queue.Queue[tuple[list[dict[str, str]], bool]]] = {}


def _deliver_question_reply(
    request_id: str, answers: list[dict[str, str]], cancelled: bool,
) -> None:
    """Called by the gateway when an AskQuestionReplyCommand arrives.
    Hands the answers to the waiting tool call via its per-request
    queue. Unknown request_id is silently dropped (the tool already
    timed out or the user replied twice — both benign)."""
    q = _pending_questions.get(request_id)
    if q is None:
        return
    try:
        q.put_nowait((answers, cancelled))
    except _queue.Full:
        pass  # only one reply expected; if full, the earlier won


def _ask_via_gateway(
    gw: Any, questions: list[dict[str, Any]], *, timeout_s: float = 600.0,
) -> str:
    """Ship an AskQuestionRequest to the TUI, wait up to ``timeout_s``
    for a matching reply, and format the answers for the model.

    Timeout default is 10 minutes — questions can sit a while if the
    user steps away. Shorter than the original ``input()`` deadlock
    (forever) by design."""
    from ..tui_gateway.events import AskQuestionRequestEvent

    request_id = _uuid.uuid4().hex
    inbox: _queue.Queue[tuple[list[dict[str, str]], bool]] = _queue.Queue(maxsize=1)
    _pending_questions[request_id] = inbox
    try:
        gw.send_event(
            AskQuestionRequestEvent(request_id=request_id, questions=questions)
        )
    except Exception:  # noqa: BLE001 — gateway momentarily unavailable
        _pending_questions.pop(request_id, None)
        return _format_no_answer(questions, reason="(could not deliver to TUI)")

    try:
        answers, cancelled = inbox.get(timeout=timeout_s)
    except _queue.Empty:
        return _format_no_answer(questions, reason="(no answer; timed out)")
    except (KeyboardInterrupt, SystemExit):
        return _format_no_answer(questions, reason="(no answer; cancelled)")
    finally:
        _pending_questions.pop(request_id, None)

    if cancelled:
        return _format_no_answer(questions, reason="(no answer; cancelled)")
    return _format_answers(questions, answers)


def _format_answers(
    questions: list[dict[str, Any]], answers: list[dict[str, str]],
) -> str:
    """Render the reply as the Q/A block the model expects."""
    # Pair questions with answers by index; missing answers (TUI
    # only returned some of them) get a sentinel.
    out: list[str] = []
    for i, q in enumerate(questions):
        q_text = q.get("question", "")
        if i < len(answers):
            a = answers[i].get("answer", "")
        else:
            a = "(no answer)"
        out.append(f"Q: {q_text}\nA: {a}")
    return "\n".join(out)


def _format_no_answer(questions: list[dict[str, Any]], *, reason: str) -> str:
    return "\n".join(
        f"Q: {q.get('question', '')}\nA: {reason}" for q in questions
    )


def _ask_one_stdin(q: dict[str, Any]) -> dict[str, str]:
    """Legacy headless path — direct stdin read. Used only when no
    TUI gateway is active (bare CLI / headless / piped invocations).
    NEVER reached in TUI mode (Ink owns stdin)."""
    question = q.get("question", "")
    options = q.get("options", []) or []
    multi = bool(q.get("multiSelect"))
    header = q.get("header", "")

    ui.console.print()
    if header:
        ui.console.print(f"[bold cyan]{header}[/]")
    ui.console.print(f"[bold]{question}[/]")
    for i, opt in enumerate(options, 1):
        label = opt.get("label", "")
        desc = opt.get("description", "")
        ui.console.print(f"  {i}. [bold]{label}[/] — [dim]{desc}[/]")
    ui.console.print(f"  {len(options) + 1}. [dim]Other (type custom answer)[/]")

    while True:
        try:
            raw = input("Choose" + (" (comma-separated)" if multi else "") + ": ").strip()
        except (EOFError, KeyboardInterrupt):
            return {"answer": "(no answer; cancelled)"}
        if not raw:
            continue
        if multi:
            picks = [p.strip() for p in raw.split(",") if p.strip()]
            try:
                idxs = [int(p) for p in picks]
            except ValueError:
                return {"answer": raw}
            answers: list[str] = []
            for i in idxs:
                if 1 <= i <= len(options):
                    answers.append(options[i - 1].get("label", ""))
                elif i == len(options) + 1:
                    custom = input("Custom answer: ").strip()
                    if custom:
                        answers.append(custom)
            return {"answer": ", ".join(answers)}
        try:
            i = int(raw)
        except ValueError:
            return {"answer": raw}
        if 1 <= i <= len(options):
            return {"answer": options[i - 1].get("label", "")}
        if i == len(options) + 1:
            custom = input("Custom answer: ").strip()
            if custom:
                return {"answer": custom}
            return {"answer": ""}
        ui.warn("invalid choice; try again")


@tool(
    name="AskUserQuestion",
    toolset="core",
    description=(
        "Use this tool when you need to ask the user questions during a "
        "task: gather preferences, clarify ambiguous instructions, or get "
        "decisions on implementation choices. Each question has 2-4 "
        "options; the user can also pick 'Other' for free-form text. "
        "Use multiSelect=true when choices are not mutually exclusive."
    ),
    parameters={
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "required": ["question", "options"],
                    "properties": {
                        "question": {"type": "string"},
                        "header": {
                            "type": "string",
                            "description": "Short label for the chip/tag (max 12 chars).",
                        },
                        "multiSelect": {"type": "boolean"},
                        "options": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "required": ["label", "description"],
                                "properties": {
                                    "label": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        },
        "required": ["questions"],
    },
)
def AskUserQuestion(questions: list[dict[str, Any]]) -> str:
    gw = ui._active_gateway
    if gw is not None:
        return _ask_via_gateway(gw, questions)
    # Headless / no-TUI fallback — direct stdin loop.
    answers: list[dict[str, str]] = []
    for q in questions:
        ans = _ask_one_stdin(q)
        answers.append({"question": q.get("question", ""), **ans})
    return "\n".join(f"Q: {a['question']}\nA: {a['answer']}" for a in answers)
