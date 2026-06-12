"""No-progress circuit breaker (runtime.py).

The identical-tool-call breaker only catches an EXACTLY repeated
(ordered) tool-call list. A model that micro-varies its arguments --
e.g. tweaking a WebSearch query every round while every search returns
"(no results)" -- never repeats an exact call, so it slips past that
breaker and can thrash for hundreds of rounds (the dogfood failure that
motivated this: 600+ WebSearch calls, the THRASH advisory firing but
never halting).

This breaker is result-shaped instead of args-shaped: it counts
CONSECUTIVE rounds that surfaced no NEW, substantive tool result (empty,
a THRASH short-circuit warning, or a duplicate of data already seen this
turn) and halts after ``cfg.max_no_progress_rounds``. A round with new
information resets it. These tests pin that behaviour via a scripted
provider plus a temporary registered tool.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from athena.agent.core import Agent
from athena.config import Config
from athena.providers.base import StreamChunk
from athena.tools import registry


@contextmanager
def _temp_tool(name: str, func: Any) -> Iterator[None]:
    """Register ``func`` as a tool for the duration of the block, then
    remove it. Dispatch only needs the tool in ``_REGISTRY`` (toolset
    filtering gates the schema sent to the model, not dispatch)."""
    registry._REGISTRY[name] = registry.Tool(
        name=name,
        description="test probe",
        parameters={"type": "object", "properties": {"q": {"type": "string"}}},
        func=func,
    )
    try:
        yield
    finally:
        registry._REGISTRY.pop(name, None)


class _ToolLoopProvider:
    """Emits one ``probe`` tool call per model round. ``vary_args`` makes
    each call's arguments unique (so the identical-tool-call breaker does
    NOT fire); otherwise every call is byte-identical."""

    name = "tool-loop"
    requires_api_key = False

    def __init__(self, *, vary_args: bool) -> None:
        self._vary = vary_args
        self.calls = 0

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
        self.calls += 1
        q = f"query {self.calls}" if self._vary else "fixed query"
        yield StreamChunk(
            "tool_call",
            {"id": f"call_{self.calls}", "name": "probe", "arguments": {"q": q}},
        )
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["tool-loop"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


def test_no_progress_trips_on_varying_args_constant_result(
    isolated_home: Path, workspace: Path
) -> None:
    """The reported failure: every round uses a DIFFERENT query (so the
    identical-tool-call breaker can't fire) but every result is the
    same "(no results)". The result-shaped breaker halts the turn."""
    cfg = Config(
        model="tool-loop",
        max_turn_steps=50,
        max_identical_tool_calls=3,  # would NOT fire — args vary every round
        max_no_progress_rounds=6,
    )
    provider = _ToolLoopProvider(vary_args=True)
    with _temp_tool("probe", lambda q="": "(no results)"):
        agent = Agent(cfg, workspace, provider=provider)
        agent.run_turn("research this")

    # Round 1's "(no results)" is novel (progress); rounds 2..7 are
    # duplicates → 6 consecutive no-progress rounds trips at round 7.
    assert provider.calls == 7
    assert agent._last_stop_reason == "circuit_breaker:no_progress"


def test_thrash_warnings_count_as_no_progress(isolated_home: Path, workspace: Path) -> None:
    """Identical args every round: the THRASH detector short-circuits the
    3rd+ call with a warning string instead of running the tool. With the
    identical-tool-call breaker disabled, those THRASH warnings must still
    register as no-progress and halt the turn (otherwise the advisory
    fires forever, exactly the dogfood bug)."""
    cfg = Config(
        model="tool-loop",
        max_turn_steps=50,
        max_identical_tool_calls=0,  # isolate the no-progress breaker
        max_no_progress_rounds=6,
    )
    provider = _ToolLoopProvider(vary_args=False)
    with _temp_tool("probe", lambda q="": "(no results)"):
        agent = Agent(cfg, workspace, provider=provider)
        agent.run_turn("research this")

    # call1 novel → progress; call2 dup → 1; calls 3..7 THRASH warnings
    # → 2..6; trips at round 7.
    assert provider.calls == 7
    assert agent._last_stop_reason == "circuit_breaker:no_progress"


def test_new_information_resets_the_counter(isolated_home: Path, workspace: Path) -> None:
    """A productive loop where every round returns NEW content must never
    trip the breaker, even past the no-progress threshold."""
    cfg = Config(
        model="tool-loop",
        max_turn_steps=50,
        max_no_progress_rounds=6,
    )

    class _Counter:
        n = 0

    def _unique(q: str = "") -> str:
        _Counter.n += 1
        return f"result #{_Counter.n}: {q}"

    provider = _ToolLoopProvider(vary_args=True)

    # Emit 10 productive tool rounds (> threshold), then finish.
    scripts = list(range(10))

    class _ProductiveThenDone(_ToolLoopProvider):
        def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
            self.calls += 1
            if self.calls > len(scripts):
                yield StreamChunk("content", "done — gathered everything.")
                yield StreamChunk("end", None)
                return
            yield StreamChunk(
                "tool_call",
                {"id": f"c{self.calls}", "name": "probe", "arguments": {"q": f"q{self.calls}"}},
            )
            yield StreamChunk("end", None)

    provider = _ProductiveThenDone(vary_args=True)
    with _temp_tool("probe", _unique):
        agent = Agent(cfg, workspace, provider=provider)
        agent.run_turn("gather facts")

    # 10 productive rounds + 1 final assistant message; breaker never fired.
    assert provider.calls == 11
    assert agent._last_stop_reason == "completed"


def test_empty_results_are_neutral_not_a_stall(isolated_home: Path, workspace: Path) -> None:
    """A round whose only tool result is EMPTY (e.g. a successful
    side-effecting command with no stdout) is uninformative but is NOT
    evidence of a loop. Such rounds must not accumulate toward the
    no-progress trip — otherwise a string of empty-output commands would
    be mistaken for thrashing."""
    cfg = Config(
        model="tool-loop",
        max_turn_steps=8,
        max_identical_tool_calls=0,
        max_no_progress_rounds=6,
    )
    provider = _ToolLoopProvider(vary_args=True)
    with _temp_tool("probe", lambda q="": ""):
        agent = Agent(cfg, workspace, provider=provider)
        agent.run_turn("run side effects")

    # Never tripped — ran to the step cap instead.
    assert provider.calls == 8
    assert agent._last_stop_reason == "step_limit"


def test_no_progress_breaker_disabled_when_zero(isolated_home: Path, workspace: Path) -> None:
    """``max_no_progress_rounds=0`` disables the breaker; the loop runs to
    the step cap instead."""
    cfg = Config(
        model="tool-loop",
        max_turn_steps=5,
        max_identical_tool_calls=0,
        max_no_progress_rounds=0,
    )
    provider = _ToolLoopProvider(vary_args=True)
    with _temp_tool("probe", lambda q="": "(no results)"):
        agent = Agent(cfg, workspace, provider=provider)
        agent.run_turn("research this")

    assert provider.calls == 5
    assert agent._last_stop_reason == "step_limit"
