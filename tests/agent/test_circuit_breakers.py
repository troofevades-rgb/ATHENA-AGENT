"""0.3.0 production-readiness circuit breakers.

Two guards layered on top of the existing ``max_turn_steps`` cap to
catch the failure modes that burn tokens without ever hitting the
step limit:

  * **Consecutive provider errors** -- if the provider returns N
    errors in a row (transport failure, 400 from a deprecated model,
    auth rejection, etc.), halt the turn instead of looping and
    burning input tokens on every attempt. Dogfood case: a model
    deprecation on a hosted backend turned every prompt into a 400
    + retry; without this guard, a misconfigured key drains the
    monthly OpenRouter budget before the operator notices.
  * **Identical tool call repetition** -- if the model emits the
    same ``(tool_name, args)`` ordered list N rounds in a row, it
    is in a stuck loop where the tool's result it can't interpret.
    Distinct calls (different tool OR different args) reset the
    counter so a legitimate iterative pass is unaffected.

Both are bounded by ``cfg.max_consecutive_provider_errors`` and
``cfg.max_identical_tool_calls`` (defaults 3). Setting either to 0
disables that breaker individually.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from athena.agent.core import Agent
from athena.agent.runtime import _tool_call_signature
from athena.config import Config
from athena.providers.base import StreamChunk

# ---------------------------------------------------------------------------
# Signature helper (pure function -- easy to pin in isolation)
# ---------------------------------------------------------------------------


def test_signature_equal_for_identical_calls() -> None:
    a = [{"function": {"name": "Read", "arguments": {"file_path": "/x"}}}]
    b = [{"function": {"name": "Read", "arguments": {"file_path": "/x"}}}]
    assert _tool_call_signature(a) == _tool_call_signature(b)


def test_signature_different_for_different_args() -> None:
    a = [{"function": {"name": "Read", "arguments": {"file_path": "/x"}}}]
    b = [{"function": {"name": "Read", "arguments": {"file_path": "/y"}}}]
    assert _tool_call_signature(a) != _tool_call_signature(b)


def test_signature_different_for_different_tool() -> None:
    a = [{"function": {"name": "Read", "arguments": {"file_path": "/x"}}}]
    b = [{"function": {"name": "Bash", "arguments": {"command": "/x"}}}]
    assert _tool_call_signature(a) != _tool_call_signature(b)


def test_signature_order_sensitive() -> None:
    """Calls in different order should NOT match -- order is part of
    the loop pattern (parallel batches can change order legitimately,
    but a stuck single-call loop won't)."""
    a = [
        {"function": {"name": "Read", "arguments": {"file_path": "/x"}}},
        {"function": {"name": "Read", "arguments": {"file_path": "/y"}}},
    ]
    b = [
        {"function": {"name": "Read", "arguments": {"file_path": "/y"}}},
        {"function": {"name": "Read", "arguments": {"file_path": "/x"}}},
    ]
    assert _tool_call_signature(a) != _tool_call_signature(b)


def test_signature_independent_of_dict_key_order() -> None:
    """A dict's iteration order shouldn't affect the signature. Two
    semantically-equal arg dicts produce the same string via
    sort_keys."""
    a = [
        {
            "function": {
                "name": "Tool",
                "arguments": {"a": 1, "b": 2, "c": 3},
            }
        }
    ]
    b = [
        {
            "function": {
                "name": "Tool",
                "arguments": {"c": 3, "a": 1, "b": 2},
            }
        }
    ]
    assert _tool_call_signature(a) == _tool_call_signature(b)


def test_signature_empty_and_none_both_yield_empty_tuple() -> None:
    assert _tool_call_signature([]) == ()
    assert _tool_call_signature(None) == ()


# ---------------------------------------------------------------------------
# End-to-end: integration providers that exercise each breaker
# ---------------------------------------------------------------------------


class _AlwaysErrorProvider:
    """Raises mid-stream on every call so ``_stream_one``'s except
    block records a provider error each round. Used to exercise the
    consecutive-provider-errors breaker."""

    name = "always-error"
    requires_api_key = False

    def __init__(self) -> None:
        self.calls = 0

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
        self.calls += 1
        # Raise before yielding anything so _stream_one's except path
        # records a provider error.
        raise RuntimeError(f"simulated upstream failure #{self.calls}")

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["always-error"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


class _StuckLoopProvider:
    """Emits the SAME tool_call ordered list on every model call so
    the identical-tool-calls breaker trips. The tool reads a missing
    file so the result is an error message -- mimics the "model
    can't interpret the result and keeps trying" pattern."""

    name = "stuck-loop"
    requires_api_key = False

    def __init__(self, missing_path: str) -> None:
        self._missing = missing_path
        self.calls = 0

    def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
        self.calls += 1
        yield StreamChunk(
            "tool_call",
            {
                "id": f"call_{self.calls}",
                "name": "Read",
                "arguments": {"file_path": self._missing},
            },
        )
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return ["stuck-loop"]

    def show_model(self, model: str) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


def test_consecutive_provider_errors_trips_breaker(
    isolated_home: Path, workspace: Path
) -> None:
    """3 simulated upstream failures in a row halts the turn with
    the ``circuit_breaker:provider_errors`` stop reason. Without
    the breaker, ``max_turn_steps`` would let the loop burn through
    25 attempts before stopping."""
    cfg = Config(
        model="always-error",
        max_turn_steps=25,
        max_consecutive_provider_errors=3,
    )
    provider = _AlwaysErrorProvider()
    agent = Agent(cfg, workspace, provider=provider)

    agent.run_turn("hello")

    # The breaker fired before the 25-step cap. Provider was called
    # exactly max_consecutive_provider_errors times.
    assert provider.calls == 3
    # Provider-error counter reflects the trip.
    assert agent.stats.provider_errors == 3


def test_consecutive_errors_breaker_disabled_when_zero(
    isolated_home: Path, workspace: Path
) -> None:
    """Setting ``max_consecutive_provider_errors=0`` disables that
    breaker; the loop runs to the step cap (or completes naturally)."""
    cfg = Config(
        model="always-error",
        max_turn_steps=5,
        max_consecutive_provider_errors=0,
    )
    provider = _AlwaysErrorProvider()
    agent = Agent(cfg, workspace, provider=provider)

    agent.run_turn("hello")

    # The breaker didn't fire -- the loop ran to ``max_turn_steps``.
    assert provider.calls == 5


def test_intermittent_errors_reset_counter(
    isolated_home: Path, workspace: Path
) -> None:
    """The consecutive counter resets on a successful call. A
    pattern like ``[error, error, success, error, error, error]``
    trips only on the THIRD trailing error, not the second
    (intermittent failures shouldn't fire the breaker)."""
    class _Flaky:
        name = "flaky"
        requires_api_key = False
        results = ["error", "error", "success", "error", "error", "error"]

        def __init__(self) -> None:
            self.calls = 0

        def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
            if self.calls >= len(self.results):
                yield StreamChunk("content", "done")
                yield StreamChunk("end", None)
                return
            outcome = self.results[self.calls]
            self.calls += 1
            if outcome == "error":
                raise RuntimeError("transient failure")
            # success -> emit a final assistant message
            yield StreamChunk("content", "intermediate")
            yield StreamChunk("end", None)

        def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
            return content, []

        def list_models(self) -> list[str]:
            return ["flaky"]

        def show_model(self, model: str) -> dict[str, Any]:
            return {}

        def close(self) -> None:
            return None

    cfg = Config(
        model="flaky",
        max_turn_steps=25,
        max_consecutive_provider_errors=3,
    )
    provider = _Flaky()
    agent = Agent(cfg, workspace, provider=provider)

    agent.run_turn("hello")

    # Sequence stops after the third trailing error: the success at
    # index 2 resets, then errors 3, 4, 5 are consecutive -- third
    # trips the breaker. But the success at index 2 was a FINAL
    # assistant message (no tool calls), so the run ended there.
    # The third trailing error never fires. Verify the success WAS
    # the exit point: provider was called 3 times (two failures +
    # the success that ended the turn).
    assert provider.calls == 3


def test_identical_tool_calls_trip_breaker(
    isolated_home: Path, workspace: Path
) -> None:
    """3 identical Read calls on the same missing file in a row
    halts the turn with ``circuit_breaker:identical_tool_calls``."""
    cfg = Config(
        model="stuck-loop",
        max_turn_steps=25,
        max_identical_tool_calls=3,
    )
    missing = workspace / "no_such_file.txt"
    provider = _StuckLoopProvider(missing_path=str(missing))
    agent = Agent(cfg, workspace, provider=provider)

    agent.run_turn("read this")

    # Breaker fired at the 3rd identical call. Without it, the loop
    # would run to max_turn_steps=25.
    assert provider.calls == 3


def test_identical_breaker_disabled_when_zero(
    isolated_home: Path, workspace: Path
) -> None:
    """Setting ``max_identical_tool_calls=0`` disables that breaker;
    the loop runs to ``max_turn_steps``."""
    cfg = Config(
        model="stuck-loop",
        max_turn_steps=5,
        max_identical_tool_calls=0,
    )
    missing = workspace / "no_such_file.txt"
    provider = _StuckLoopProvider(missing_path=str(missing))
    agent = Agent(cfg, workspace, provider=provider)

    agent.run_turn("read this")

    # Without the breaker, ran to ``max_turn_steps``.
    assert provider.calls == 5


def test_different_args_reset_identical_counter(
    isolated_home: Path, workspace: Path
) -> None:
    """A legitimate iterative pass (reading three different files)
    does NOT trip the breaker even though every call uses the same
    tool. Only IDENTICAL ``(tool_name, args)`` ordered lists count."""
    workspace.joinpath("a.txt").write_text("a", encoding="utf-8")
    workspace.joinpath("b.txt").write_text("b", encoding="utf-8")
    workspace.joinpath("c.txt").write_text("c", encoding="utf-8")

    class _IterativeReader:
        name = "iterative"
        requires_api_key = False
        files = ["a.txt", "b.txt", "c.txt"]

        def __init__(self, workspace: Path) -> None:
            self.calls = 0
            self._workspace = workspace

        def stream_chat(self, **kwargs: Any) -> Iterator[StreamChunk]:
            self.calls += 1
            if self.calls > len(self.files):
                # All three reads done -- emit final.
                yield StreamChunk("content", "done")
                yield StreamChunk("end", None)
                return
            target = self._workspace / self.files[self.calls - 1]
            yield StreamChunk(
                "tool_call",
                {
                    "id": f"call_{self.calls}",
                    "name": "Read",
                    "arguments": {"file_path": str(target)},
                },
            )
            yield StreamChunk("end", None)

        def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
            return content, []

        def list_models(self) -> list[str]:
            return ["iterative"]

        def show_model(self, model: str) -> dict[str, Any]:
            return {}

        def close(self) -> None:
            return None

    cfg = Config(
        model="iterative",
        max_turn_steps=10,
        max_identical_tool_calls=2,  # Aggressive -- would catch true loops fast.
    )
    provider = _IterativeReader(workspace)
    agent = Agent(cfg, workspace, provider=provider)

    agent.run_turn("read each")

    # All three different reads went through + final assistant call.
    assert provider.calls == 4
