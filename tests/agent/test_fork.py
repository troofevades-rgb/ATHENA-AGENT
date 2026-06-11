"""``Agent.fork()`` daemon-thread isolation (T1-04.6).

Forks run on a single ``threading.Thread(daemon=True)`` that is
``join()``-ed before ``fork()`` returns. Inside the runner the fork
installs ``AUTO_DENY``, sets its own ``write_origin``, optionally
builds an auxiliary provider, and redirects stdout/stderr to per-call
buffers.

The existing ``tests/test_fork_full.py`` covers end-to-end shape;
this file unit-tests the isolation invariants individually so a
regression in any one of them surfaces with a precise failure.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from athena.agent import auxiliary_client as aux_mod
from athena.agent.core import Agent
from athena.agent.fork import ForkAction, _extract_actions
from athena.config import Config
from athena.provenance import (
    BACKGROUND_REVIEW,
    CURATOR,
    FOREGROUND,
    get_current_write_origin,
)
from athena.providers import _REGISTRY
from athena.providers.base import StreamChunk
from athena.safety.approval_callback import AUTO_DENY, get_approval_callback

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Scripted provider that captures ContextVar state at stream time
# ---------------------------------------------------------------------------


class ObservingProvider:
    """Provider stand-in that records the ContextVar / callback state
    visible from inside the fork's thread."""

    instances: list[ObservingProvider] = []

    def __init__(self, host: str = "", timeout: float = 600.0, response: str = "fork done") -> None:
        self.host = host
        self.response = response
        self.observations: list[dict[str, Any]] = []
        self.closed = False
        ObservingProvider.instances.append(self)

    def show_model(self, model: str) -> dict[str, Any]:
        return {"system": ""}

    def list_models(self) -> list[str]:
        return []

    def stream_chat(self, *, model: str, messages: list[dict], **kwargs: Any):
        self.observations.append(
            {
                "model": model,
                "write_origin": get_current_write_origin(),
                "approval_callback": get_approval_callback(),
                "thread_name": threading.current_thread().name,
                "thread_daemon": threading.current_thread().daemon,
            }
        )
        if self.response:
            yield StreamChunk("content", self.response)
        yield StreamChunk(
            "usage",
            {
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "prompt_eval_count": 1,
                "eval_count": 2,
            },
        )
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def observing_provider(monkeypatch: pytest.MonkeyPatch) -> type[ObservingProvider]:
    """Replace the ``ollama`` provider in the registry with
    ObservingProvider for the test's duration."""
    ObservingProvider.instances = []
    saved = _REGISTRY.get("ollama")
    _REGISTRY["ollama"] = ObservingProvider  # type: ignore[assignment]
    monkeypatch.setattr(aux_mod, "OllamaProvider", ObservingProvider, raising=False)
    yield ObservingProvider
    if saved is not None:
        _REGISTRY["ollama"] = saved
    else:
        _REGISTRY.pop("ollama", None)


@pytest.fixture
def parent_agent(isolated_home: Path, observing_provider: type[ObservingProvider]) -> Agent:
    cfg = Config(model="parent-model", ollama_host="http://parent.example:11434")
    return Agent(cfg, isolated_home, model="parent-model")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fork_runs_in_daemon_thread(parent_agent: Agent) -> None:
    """The fork's ``stream_chat`` is invoked from a daemon thread whose
    name carries the ``athena-fork-`` prefix."""
    parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    fork_instances = [p for p in ObservingProvider.instances if p.observations]
    # The most recent instance is the fork's auxiliary client.
    assert fork_instances, "fork did not invoke ObservingProvider.stream_chat"
    obs = fork_instances[-1].observations[-1]
    assert obs["thread_daemon"] is True
    assert obs["thread_name"].startswith("athena-fork-"), obs["thread_name"]


def test_fork_has_own_write_origin(parent_agent: Agent) -> None:
    """The fork's ``write_origin`` is the value passed into ``fork()``;
    the parent's stays at ``FOREGROUND``."""
    parent_agent.fork(
        enabled_toolsets=["core"],
        system_addendum="",
        write_origin=CURATOR,
    )
    fork_obs = [o for p in ObservingProvider.instances for o in p.observations]
    # The fork's observation has CURATOR; the parent has not streamed
    # anything yet but the contextvar at the parent thread should still
    # be FOREGROUND.
    assert any(o["write_origin"] == CURATOR for o in fork_obs), fork_obs
    assert get_current_write_origin() == FOREGROUND


def test_fork_defaults_write_origin_to_background_review(
    parent_agent: Agent,
) -> None:
    """Without an explicit ``write_origin=``, ``BACKGROUND_REVIEW`` is
    the default — matches Phase 4's background-review fork semantics."""
    parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    fork_obs = [o for p in ObservingProvider.instances for o in p.observations]
    assert any(o["write_origin"] == BACKGROUND_REVIEW for o in fork_obs)


def test_fork_installs_auto_deny_approval(parent_agent: Agent) -> None:
    """The approval callback visible from the fork's stream_chat is
    ``AUTO_DENY``; the parent's stays at the default interactive prompt."""
    # Capture parent's callback before the fork.
    parent_cb = get_approval_callback()
    assert parent_cb is not AUTO_DENY

    parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    fork_obs = [o for p in ObservingProvider.instances for o in p.observations]
    assert any(o["approval_callback"] is AUTO_DENY for o in fork_obs), (
        f"AUTO_DENY not installed in fork; callbacks observed: "
        f"{[o['approval_callback'] for o in fork_obs]}"
    )
    # Parent's callback is unchanged after the fork joins.
    assert get_approval_callback() is parent_cb


def test_fork_extracts_structured_actions() -> None:
    """``_extract_actions`` parses tool-result messages whose content is
    a JSON dict with ``success: true`` + ``action`` into ``ForkAction``
    records; free-form / failure results are skipped."""
    import json as _json

    messages = [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "calling skill_manage"},
        {
            "role": "tool",
            "content": _json.dumps(
                {
                    "success": True,
                    "action": "created",
                    "target": "skill",
                    "skill_name": "test-skill",
                    "message": "made it",
                }
            ),
        },
        {
            "role": "tool",
            "content": _json.dumps(
                {
                    "success": False,
                    "action": "updated",
                    "target": "skill",
                    "skill_name": "broken",
                }
            ),
        },
        {"role": "tool", "content": "free-form text result, no JSON"},
        {
            "role": "tool",
            "content": _json.dumps(
                {
                    "success": True,
                    "action": "patched",
                    "target": "memory",
                    "memory_name": "note-1",
                }
            ),
        },
    ]
    actions = _extract_actions(messages)
    assert len(actions) == 2
    assert actions[0] == ForkAction(
        action="created", target="skill", name="test-skill", detail="made it"
    )
    assert actions[1] == ForkAction(action="patched", target="memory", name="note-1", detail=None)


def test_fork_aligns_tool_result_nonce_with_pinned_prompt(
    parent_agent: Agent, monkeypatch
) -> None:
    """Security regression: fork() pins the PARENT's system prompt (for
    prefix-cache warmth), and that prompt names the parent's tool-result
    nonce in its prompt-injection containment contract. The child must
    therefore wrap its tool results with the SAME nonce — otherwise the
    [TOOL_RESULT.<nonce>] markers the model is told to trust never
    appear, weakening containment where the auto-approving Agent-tool
    sub-agent runs."""
    import athena.agent.core as core_mod

    captured: dict[str, Agent] = {}
    real_agent = core_mod.Agent

    class _CapturingAgent(real_agent):  # type: ignore[valid-type,misc]
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            captured["child"] = self

    monkeypatch.setattr(core_mod, "Agent", _CapturingAgent)

    # The parent has a system prompt + nonce (built in Agent.__init__).
    assert parent_agent.messages[0]["role"] == "system"
    parent_nonce = parent_agent._tool_result_nonce
    assert parent_nonce

    parent_agent.fork(enabled_toolsets=["core"], system_addendum="")

    child = captured["child"]
    # Child uses the parent's prompt AND the parent's nonce — aligned,
    # so the wrapped markers match the containment contract in the prompt.
    assert child._tool_result_nonce == parent_nonce
    # And the pinned prompt is in fact the parent's.
    assert child.messages[0]["content"] == parent_agent.messages[0]["content"]


def test_fork_does_not_share_provider_client(parent_agent: Agent) -> None:
    """With ``auxiliary_client=True`` (the default), the fork's provider
    is a *distinct* instance from the parent's — separate httpx client,
    no shared connection-pool / KV-cache pollution."""
    parent_provider = parent_agent.client
    parent_agent.fork(
        enabled_toolsets=["core"],
        system_addendum="",
        auxiliary_client=True,
    )
    # The fork registered its own ObservingProvider instance; assert
    # at least two instances exist (parent + fork) and the fork's
    # observations did not land on the parent.
    assert len(ObservingProvider.instances) >= 2
    fork_observers = [
        p for p in ObservingProvider.instances if p is not parent_provider and p.observations
    ]
    assert fork_observers, "fork reused parent's provider client"


def test_fork_shares_client_when_auxiliary_false(parent_agent: Agent) -> None:
    """``auxiliary_client=False`` makes the fork share the parent's
    client; observations land on the parent provider instance."""
    parent_provider = parent_agent.client
    before = len(getattr(parent_provider, "observations", []))
    parent_agent.fork(
        enabled_toolsets=["core"],
        system_addendum="",
        auxiliary_client=False,
    )
    after = len(parent_provider.observations)  # type: ignore[attr-defined]
    assert after > before, (
        "fork(auxiliary_client=False) should have streamed on the parent's provider"
    )


# ---------------------------------------------------------------------------
# T2-08: in_fork_context ContextVar is set inside the fork runner
# ---------------------------------------------------------------------------


def test_fork_sets_in_fork_context_for_clarify(parent_agent: Agent) -> None:
    """The fork's runner sets athena.tools.clarify.in_fork_context to
    True before run_until_done, so a clarify call inside the fork
    sees the fork mode and AUTO_DENYs instead of blocking on stdin."""
    from athena.tools.clarify import in_fork_context

    captured: dict[str, bool] = {}

    # Patch the ObservingProvider so each call records the value of
    # in_fork_context at stream_chat time — gives us per-thread proof.
    original_stream = ObservingProvider.stream_chat

    def _instrumented_stream(self, **kwargs):
        captured["in_fork"] = in_fork_context.get()
        return original_stream(self, **kwargs)

    ObservingProvider.stream_chat = _instrumented_stream  # type: ignore[method-assign]
    try:
        # Parent is foreground -> in_fork_context is False here.
        assert in_fork_context.get() is False
        parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    finally:
        ObservingProvider.stream_chat = original_stream  # type: ignore[method-assign]

    assert captured.get("in_fork") is True, (
        "fork runner did not set in_fork_context to True; clarify would "
        "block on stdin from inside a background fork"
    )
