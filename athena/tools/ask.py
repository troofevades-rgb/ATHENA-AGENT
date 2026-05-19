"""AskUserQuestion tool — pause the agent loop and prompt the user.

Mirrors Claude Code's AskUserQuestion. Models call this when they need a
decision from the user mid-task (rather than guessing). The tool blocks the
agent loop until the user responds.

Each question has 2-4 options; the user can also type free-form text via the
'Other' option. multiSelect=true lets the user pick multiple.
"""

from __future__ import annotations

from typing import Any

from .. import ui
from .registry import tool


def _ask_one(q: dict[str, Any]) -> dict[str, str]:
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
            # Parse comma-separated choices
            picks = [p.strip() for p in raw.split(",") if p.strip()]
            try:
                idxs = [int(p) for p in picks]
            except ValueError:
                return {"answer": raw}  # treat as custom text
            answers: list[str] = []
            for i in idxs:
                if 1 <= i <= len(options):
                    answers.append(options[i - 1].get("label", ""))
                elif i == len(options) + 1:
                    custom = input("Custom answer: ").strip()
                    if custom:
                        answers.append(custom)
            return {"answer": ", ".join(answers)}
        # single
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
    answers: list[dict[str, str]] = []
    for q in questions:
        ans = _ask_one(q)
        answers.append({"question": q.get("question", ""), **ans})
    # Format response back to the model
    return "\n".join(f"Q: {a['question']}\nA: {a['answer']}" for a in answers)
