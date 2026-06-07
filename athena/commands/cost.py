"""``/cost`` — show token usage and elapsed time for this session."""

from __future__ import annotations

import time
from typing import Any

from .. import ui
from . import command


@command("cost")
def cmd_cost(agent: Any, arg: str = "") -> str:
    s = agent.stats
    elapsed = time.time() - s.started
    ui.console.print(
        f"turns: {s.turns}  tool calls: {s.tool_calls}\n"
        f"prompt tokens: {s.prompt_tokens}  eval tokens: {s.eval_tokens}\n"
        f"elapsed: {elapsed:.1f}s"
    )
    return ""
