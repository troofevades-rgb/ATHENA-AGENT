"""``memory_query`` — natural-language recall over the user-model
backend (auto-extracted facts) plus the user-authored memory store.

Returns synthesized prose plus a provenance footer the agent can
use to weight the answer.
"""

from __future__ import annotations

import asyncio

from . import file_ops
from .registry import tool


def _build_llm_call(agent):
    """Wrap the agent's sync streaming provider as an async
    ``(system, user) -> str`` callable for the user-model backend."""

    extract_model = (
        agent.cfg.user_model.extract_model
        if agent.cfg.user_model.extract_model
        else agent.model
    )

    async def _call(system_prompt: str, user_prompt: str) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        def _sync_stream() -> str:
            chunks: list[str] = []
            for chunk in agent.provider.stream_chat(
                model=extract_model,
                messages=messages,
                tools=None,
                max_tokens=2000,
                num_ctx=agent.cfg.context_window,
            ):
                if chunk.kind == "content":
                    payload = chunk.payload or ""
                    if isinstance(payload, str):
                        chunks.append(payload)
            return "".join(chunks)

        # ``stream_chat`` is sync; run on a worker thread so the
        # event loop doesn't block.
        return await asyncio.to_thread(_sync_stream)

    return _call


@tool(
    name="memory_query",
    toolset="memory",
    description=(
        "Ask a natural-language question about what's known about "
        "the user and their project. Returns synthesized prose plus "
        "the fact IDs that backed the answer (tagged ``[auto]`` for "
        "facts the agent extracted from prior sessions, ``[user]`` "
        "for facts the user wrote themselves via write_memory). "
        "Use BEFORE making assumptions about preferences, workflow, "
        "or tooling — cheaper than guessing wrong. Says so plainly "
        "if no facts support an answer."
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "The question to ask. Phrase it concretely — "
                    "'does this user prefer terse responses?' beats "
                    "'tell me about the user'."
                ),
            }
        },
        "required": ["question"],
    },
)
def memory_query(question: str) -> str:
    try:
        from ..agent.core import get_current_agent
        from ..user_model import get_user_model_backend
    except ImportError as e:
        return f"ERROR: user_model unavailable ({e})"

    agent = get_current_agent()
    if agent is None:
        return "ERROR: no active agent (memory_query must run inside a session)"

    try:
        backend = get_user_model_backend(
            agent.cfg,
            llm_call=_build_llm_call(agent),
            workspace=file_ops._WORKSPACE,
        )
    except (ValueError, NotImplementedError) as e:
        return f"ERROR: {e}"

    try:
        result = asyncio.run(backend.query(question))
    except RuntimeError:
        # Already inside an event loop (rare in athena's sync REPL,
        # but possible under tests). Fall back to a fresh loop.
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(backend.query(question))
        finally:
            loop.close()

    lines = [result.answer]
    if result.sources:
        lines.append("")
        lines.append(f"sources: {', '.join(result.sources)}")
    return "\n".join(lines)
