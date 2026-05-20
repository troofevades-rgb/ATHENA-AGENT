"""Long-session integration test (T2-04.8).

Drives an Agent against a scripted provider through enough turns
that the compressor's watermark trigger has to fire at least once;
asserts the session keeps running and the final context stays
under the configured window.

The provider here returns short fixed-size responses; the model
fixture's "long" property comes from the user input each turn,
which inflates ``self.messages`` predictably and lets us assert
deterministically that compression must happen.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from athena.agent.context_compressor import total_tokens
from athena.agent.core import Agent
from athena.config import Config
from athena.providers.base import StreamChunk


class _ScriptedProvider:
    """Yields a tiny fixed response on every call. Mirrors enough of
    the Provider ABC for Agent to drive it; counts stream_chat calls
    so the test can assert how many round-trips happened."""

    name = "scripted"
    requires_api_key = False

    def __init__(self) -> None:
        self.calls = 0
        # Stream of compressor summariser calls have larger output;
        # routine turns are tiny.
        self._summarizer_response = (
            "## Resolved questions\n(none)\n\n"
            "## Pending questions\n(none)\n\n"
            "## Decisions made\n(none)\n\n"
            "## Tool outputs of lasting value\n(none)\n\n"
            "## Remaining work\n(none)\n"
        )

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
        self.calls += 1
        msgs = kwargs.get("messages") or []
        # Heuristic: if the first system message contains the
        # summariser preamble, we're being asked to summarise.
        is_summarizer_call = False
        if msgs and msgs[0].get("role") == "system":
            sys_content = str(msgs[0].get("content", ""))
            if "SOURCE MATERIAL" in sys_content:
                is_summarizer_call = True

        if is_summarizer_call:
            for piece in self._summarizer_response.split(" "):
                yield StreamChunk("content", piece + " ")
            yield StreamChunk("end", None)
            return

        yield StreamChunk("content", "ack")
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["scripted"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


def _make_agent(workspace: Path, provider: Any, **cfg_overrides: Any) -> Agent:
    cfg = Config(model="scripted")
    for k, v in cfg_overrides.items():
        setattr(cfg, k, v)
    return Agent(cfg, workspace, provider=provider)


def test_long_session_triggers_compression_and_completes(
    isolated_home: Path, workspace: Path
) -> None:
    """A 60-turn session with deliberately bloated user messages
    triggers compression at least once and finishes without raising."""
    provider = _ScriptedProvider()
    # Small window + aggressive watermark so compression fires quickly.
    agent = _make_agent(
        workspace,
        provider,
        context_window=4_000,
        context_compress_watermark=0.5,
        tail_protection_ratio=0.2,
        summary_budget_ratio=0.05,
        summary_budget_cap_tokens=200,
        max_turn_steps=1,  # 1 step per turn: no tool-round loop
    )

    initial_messages_count = len(agent.messages)

    # Each user message is ~800 chars (~200 tokens); 60 turns
    # accumulate ~12k tokens worth — well past the 50% watermark
    # of a 4k window.
    big_payload = "context-builder " * 50  # ~800 chars
    for i in range(60):
        agent.run_turn(f"turn {i}: {big_payload}")

    # At least one compression must have happened: a synthetic
    # summary message (role=system content starting with
    # "[Compressed summary of turns") is in agent.messages.
    summary_msgs = [
        m
        for m in agent.messages
        if m.get("role") == "system"
        and isinstance(m.get("content"), str)
        and m["content"].startswith("[Compressed summary of turns")
    ]
    assert summary_msgs, (
        f"no compression summary found; agent.messages has "
        f"{len(agent.messages)} messages, started with {initial_messages_count}"
    )

    # The final session token count must be under the configured
    # window. With watermark=0.5 and aggressive compression we should
    # stay well under 4_000 tokens.
    final_tokens = total_tokens(agent.messages)
    assert final_tokens < agent.cfg.context_window, (
        f"final context {final_tokens} tokens >= window "
        f"{agent.cfg.context_window} — compression didn't keep up"
    )

    # And the agent kept running: 60 user turns are in history.
    user_count = sum(1 for m in agent.messages if m.get("role") == "user")
    assert user_count >= 1, "user messages disappeared entirely"


def test_compression_disabled_via_high_watermark(isolated_home: Path, workspace: Path) -> None:
    """Setting context_compress_watermark above 1.0 disables proactive
    compression — the agent runs without ever calling the summariser."""
    provider = _ScriptedProvider()
    agent = _make_agent(
        workspace,
        provider,
        context_window=4_000,
        context_compress_watermark=10.0,  # never trigger
        max_turn_steps=1,
    )

    for i in range(10):
        agent.run_turn(f"turn {i}: " + ("x" * 500))

    # No synthetic summary in history.
    summary_msgs = [
        m
        for m in agent.messages
        if m.get("role") == "system"
        and isinstance(m.get("content"), str)
        and m["content"].startswith("[Compressed summary of turns")
    ]
    assert summary_msgs == [], "compression fired despite high watermark"
