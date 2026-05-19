"""/compact — summarize the conversation history and replace it with the summary.

Useful when the context is filling up. Asks the model to produce a tight
summary of work done so far, then replaces the message history (after the
system prompt) with that summary as a single user message.
"""

from __future__ import annotations

from .. import ui
from . import command

_SUMMARY_PROMPT = """\
Summarize this conversation so far for context-window compaction. Cover:
- What the user asked for (the actual goal, not just the surface words)
- What investigation has happened (key findings, ruled-out paths)
- What changes have been made (files edited, with file paths)
- What's still open (unresolved questions, pending tasks)

Be concise. Bullet points. No filler. The summary will replace the prior
conversation, so include anything that's load-bearing for what comes next.
"""


@command("compact")
def cmd_compact(agent, arg: str = "") -> str:
    if len(agent.messages) <= 2:
        ui.info("nothing to compact")
        return ""
    # Have the model write a summary using a fresh request
    agent.messages.append({"role": "user", "content": _SUMMARY_PROMPT})
    text, _, _ = agent._stream_one()
    if not text.strip():
        ui.warn("compaction failed; conversation unchanged")
        agent.messages.pop()  # remove the prompt we appended
        return ""
    system = agent.messages[0]
    summary_msg = {
        "role": "user",
        "content": f"[Compacted summary of prior conversation]\n\n{text}",
    }
    agent.messages = [system, summary_msg]
    ui.info(f"compacted: {len(text)} chars summary")
    return ""
