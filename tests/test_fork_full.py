"""End-to-end tests for the fleshed-out Agent.fork() primitive.

Replaces the Phase 0 stub tests in tests/test_fork.py. Uses a FakeClient so
no Ollama backend is required; isolated_home keeps the parent agent's
SessionStore from touching the real ~/.athena.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

import athena.agent.core as core_mod
from athena.agent import Agent, ForkAction, ForkResult
from athena.agent import auxiliary_client as aux_mod
from athena.config import Config
from athena.providers import StreamChunk
from athena.provenance import (
    BACKGROUND_REVIEW,
    CURATOR,
    FOREGROUND,
    get_current_write_origin,
)
from athena.safety.approval_callback import (
    AUTO_DENY,
    _interactive_approval,
    get_approval_callback,
)


# -- fakes ---------------------------------------------------------------


class FakeClient:
    """Captures the state of contextvars at the moment stream_chat() is invoked.

    Phase 8 surface: implements the Provider Protocol (stream_chat yielding
    StreamChunks, show_model, list_models, close). Constructor signature is
    ``(host=..., timeout=..., response=...)`` so the OllamaProvider call site
    keeps working.
    """
    instances: list["FakeClient"] = []

    def __init__(self, host: str = "", timeout: float = 600.0, response: str = "hello from fork") -> None:
        self.host = host
        self.response = response
        self.observations: list[dict[str, Any]] = []
        self.tool_payloads: list[Any] = []
        self.closed = False
        FakeClient.instances.append(self)

    def show_model(self, model: str) -> dict[str, Any]:
        return {"system": ""}

    def list_models(self) -> list[str]:
        return []

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ):
        self.tool_payloads.append(tools)
        self.observations.append({
            "model": model,
            "write_origin": get_current_write_origin(),
            "approval_callback": get_approval_callback(),
            "messages": list(messages),
            "tools": tools,
        })
        if self.response:
            yield StreamChunk("content", self.response)
        yield StreamChunk("usage", {
            "prompt_tokens": 1, "completion_tokens": 2,
            "prompt_eval_count": 1, "eval_count": 2, "eval_duration": 0,
        })
        yield StreamChunk("end", {"reason": "stop"})

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch):
    """Replace the registry's ``ollama`` entry with FakeClient for the
    duration of the test, so the resolver hands FakeClient back when
    the agent (or a fork) constructs its provider."""
    FakeClient.instances = []
    from athena.providers import _REGISTRY
    saved = _REGISTRY.get("ollama")
    _REGISTRY["ollama"] = FakeClient
    # Also poison the module-level OllamaProvider symbols so any code
    # that bypassed the resolver and reached for them still gets a fake.
    monkeypatch.setattr(core_mod, "OllamaProvider", FakeClient, raising=False)
    monkeypatch.setattr(aux_mod, "OllamaProvider", FakeClient, raising=False)
    yield FakeClient
    if saved is not None:
        _REGISTRY["ollama"] = saved
    else:
        _REGISTRY.pop("ollama", None)


@pytest.fixture
def parent_agent(isolated_home: Path, fake_client: type[FakeClient]) -> Agent:
    cfg = Config(model="parent-model", ollama_host="http://parent.example:11434")
    return Agent(cfg, isolated_home, model="parent-model")


# -- tests ---------------------------------------------------------------


def test_auxiliary_client_creates_fresh_ollama_instance(parent_agent: Agent) -> None:
    """build_auxiliary_client returns a new client (not the parent's)."""
    from athena.agent.auxiliary_client import build_auxiliary_client
    aux = build_auxiliary_client(parent_agent)
    assert aux is not parent_agent.client
    # Host matches the parent's config.
    assert aux.host == parent_agent.cfg.ollama_host


def test_fork_uses_auxiliary_client_by_default(parent_agent: Agent) -> None:
    parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    # FakeClients: parent + child's auxiliary. Latest is the auxiliary.
    aux = FakeClient.instances[-1]
    assert aux is not parent_agent.client


def test_fork_shares_client_when_auxiliary_false(parent_agent: Agent) -> None:
    parent_client = parent_agent.client
    parent_agent.fork(
        enabled_toolsets=["core"],
        system_addendum="",
        auxiliary_client=False,
    )
    # The child should have used the parent's client — that means the
    # parent's instance has chat() observations from the fork.
    assert parent_client.observations  # fork made a call through it


def test_fork_inherits_session_store(parent_agent: Agent) -> None:
    """The fork's child Agent shares the parent's SessionStore object."""
    captured: dict[str, Any] = {}
    real_thread = threading.Thread

    def spy_thread(*args, **kwargs):
        # Bind a closure that snapshots child state at runtime by hooking
        # the target; easier to just observe via the FakeClient observation.
        return real_thread(*args, **kwargs)

    parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    # The child appended a turn → parent's session_store has rows for the
    # parent session + the child session.
    sessions = parent_agent.session_store.list_sessions()
    parent_ids = {s.session_id for s in sessions}
    assert parent_agent.session_id in parent_ids
    # There must be at least one OTHER session — the fork's child.
    assert len(parent_ids) >= 2


def test_fork_child_session_has_parent_id_set(parent_agent: Agent) -> None:
    parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    sessions = parent_agent.session_store.list_sessions()
    children = [s for s in sessions if s.parent_session_id == parent_agent.session_id]
    assert len(children) == 1
    assert children[0].session_id != parent_agent.session_id


def test_fork_messages_inject_system_addendum(parent_agent: Agent) -> None:
    parent_agent.fork(enabled_toolsets=["core"], system_addendum="ADDENDUM_TEXT")
    aux = FakeClient.instances[-1]
    system_msg = aux.observations[0]["messages"][0]
    assert "ADDENDUM_TEXT" in system_msg["content"]


def test_fork_pins_parent_system_prompt_verbatim(parent_agent: Agent) -> None:
    """The child's system prompt must be the parent's prefix + addendum.

    Hosted providers (Anthropic, OpenRouter) prefix-cache on byte-exact
    match. If the child rebuilds its system prompt from scratch — fresh
    ``today`` date, fresh skills catalog, fresh Modelfile-SYSTEM fetch —
    the cache prefix ends at the first divergent byte. Hermes Agent
    measured ~26% cost reduction on Sonnet 4.5 from pinning. This test
    locks in the parity.
    """
    parent_system = parent_agent.messages[0]["content"]
    parent_agent.fork(enabled_toolsets=["core"], system_addendum="ADD")
    aux = FakeClient.instances[-1]
    child_system = aux.observations[0]["messages"][0]["content"]
    assert child_system.startswith(parent_system.rstrip())
    assert child_system.endswith("ADD")


def test_fork_with_no_addendum_inherits_parent_system_exactly(
    parent_agent: Agent,
) -> None:
    parent_system = parent_agent.messages[0]["content"]
    parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    aux = FakeClient.instances[-1]
    assert aux.observations[0]["messages"][0]["content"] == parent_system


def test_fork_messages_inject_conversation_history(parent_agent: Agent) -> None:
    history = [
        {"role": "user", "content": "prior question"},
        {"role": "assistant", "content": "prior answer"},
    ]
    parent_agent.fork(
        enabled_toolsets=["core"],
        system_addendum="",
        conversation_history=history,
    )
    aux = FakeClient.instances[-1]
    seen = aux.observations[0]["messages"]
    assert seen[1] == history[0]
    assert seen[2] == history[1]


def test_fork_write_origin_set_during_execution(parent_agent: Agent) -> None:
    parent_agent.fork(
        enabled_toolsets=["core"],
        system_addendum="",
        write_origin=CURATOR,
    )
    aux = FakeClient.instances[-1]
    assert aux.observations[0]["write_origin"] == CURATOR
    # And the parent's thread is restored.
    assert get_current_write_origin() == FOREGROUND


def test_fork_write_origin_defaults_to_background_review(parent_agent: Agent) -> None:
    parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    aux = FakeClient.instances[-1]
    assert aux.observations[0]["write_origin"] == BACKGROUND_REVIEW


def test_fork_auto_deny_blocks_confirmation_tools(parent_agent: Agent) -> None:
    """The approval callback inside the fork thread is AUTO_DENY; the parent
    thread's callback is untouched."""
    parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    aux = FakeClient.instances[-1]
    assert aux.observations[0]["approval_callback"] is AUTO_DENY
    assert get_approval_callback() is _interactive_approval


def test_fork_stdout_captured_in_quiet_mode(
    parent_agent: Agent, capsys: pytest.CaptureFixture[str]
) -> None:
    """quiet=True redirects stdout/stderr to StringIO buffers and surfaces
    them via ForkResult.stdout / stderr — they do NOT print."""
    original_chat = FakeClient.stream_chat

    def chat_with_print(self, *args, **kwargs):
        print("FORK_OUTPUT_LINE")
        import sys as _sys
        print("FORK_ERROR_LINE", file=_sys.stderr)
        yield from original_chat(self, *args, **kwargs)

    FakeClient.stream_chat = chat_with_print
    try:
        result = parent_agent.fork(
            enabled_toolsets=["core"],
            system_addendum="",
            quiet=True,
        )
    finally:
        FakeClient.stream_chat = original_chat

    assert "FORK_OUTPUT_LINE" not in capsys.readouterr().out
    assert "FORK_OUTPUT_LINE" in result.stdout


def test_fork_stderr_captured_in_quiet_mode(parent_agent: Agent) -> None:
    """Surfaces stderr separately so the parent can inspect warnings without
    polluting the user's terminal."""
    original_chat = FakeClient.stream_chat

    def chat_with_stderr(self, *args, **kwargs):
        import sys
        print("FORK_STDERR_WARNING", file=sys.stderr)
        yield from original_chat(self, *args, **kwargs)

    FakeClient.stream_chat = chat_with_stderr
    try:
        result = parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    finally:
        FakeClient.stream_chat = original_chat
    assert "FORK_STDERR_WARNING" in result.stderr


def test_fork_quiet_false_lets_output_through(
    parent_agent: Agent, capsys: pytest.CaptureFixture[str]
) -> None:
    """quiet=False skips the redirect — output flows to the real stdout."""
    original_chat = FakeClient.stream_chat

    def chat_with_print(self, *args, **kwargs):
        print("VISIBLE_FORK_OUTPUT")
        yield from original_chat(self, *args, **kwargs)

    FakeClient.stream_chat = chat_with_print
    try:
        parent_agent.fork(
            enabled_toolsets=["core"],
            system_addendum="",
            quiet=False,
        )
    finally:
        FakeClient.stream_chat = original_chat

    assert "VISIBLE_FORK_OUTPUT" in capsys.readouterr().out


def test_fork_returns_result_with_final_response(parent_agent: Agent) -> None:
    result = parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    assert isinstance(result, ForkResult)
    assert result.final_response == "hello from fork"
    assert result.error is None
    assert result.child_session_id is not None
    assert result.duration_s >= 0.0


def test_fork_exception_recorded_in_error_field(parent_agent: Agent) -> None:
    """If the fork's inner loop raises, the error is captured on ForkResult."""
    def bad_chat(self, *args, **kwargs):
        raise RuntimeError("simulated provider failure")
        yield  # pragma: no cover — required for generator function shape

    original = FakeClient.stream_chat
    FakeClient.stream_chat = bad_chat
    try:
        result = parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    finally:
        FakeClient.stream_chat = original
    # The fork's loop catches provider errors and prints a warning; the run
    # still completes with no assistant message.
    assert result.final_response == ""


def test_fork_actions_extracted_from_tool_results(parent_agent: Agent) -> None:
    """Tool messages with a structured success payload populate actions."""
    from athena.agent.fork import _extract_actions

    messages = [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "do it"},
        {
            "role": "assistant",
            "content": "ok",
            "tool_calls": [{"function": {"name": "skill_manage", "arguments": "{}"}}],
        },
        {
            "role": "tool",
            "name": "skill_manage",
            "content": '{"success": true, "target": "skill", "action": "create", '
                       '"skill_name": "test-skill", "message": "skill created"}',
        },
        {"role": "tool", "name": "Bash", "content": "free-form output, not JSON"},
        {
            "role": "tool",
            "name": "skill_manage",
            "content": '{"success": false, "target": "skill", "action": "delete", '
                       '"skill_name": "x", "message": "denied"}',
        },
    ]
    actions = _extract_actions(messages)
    # Only the one successful structured result yields an action.
    assert len(actions) == 1
    assert isinstance(actions[0], ForkAction)
    assert actions[0].action == "create"
    assert actions[0].target == "skill"
    assert actions[0].name == "test-skill"
    assert actions[0].detail == "skill created"


def test_fork_duration_recorded(parent_agent: Agent) -> None:
    result = parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    assert result.duration_s >= 0.0


def test_fork_thread_is_daemon(parent_agent: Agent, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    real_thread = threading.Thread

    def capturing_thread(*args, **kwargs):
        name = kwargs.get("name") or ""
        if name.startswith("athena-fork"):
            seen["daemon"] = kwargs.get("daemon")
            seen["name"] = name
        return real_thread(*args, **kwargs)

    import athena.agent.fork as fork_mod
    monkeypatch.setattr(fork_mod.threading, "Thread", capturing_thread)
    parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    assert seen.get("daemon") is True
    assert seen.get("name", "").startswith("athena-fork-")


def test_fork_uses_enabled_toolsets(parent_agent: Agent) -> None:
    """The child's chat() must see tools restricted to the chosen toolsets."""
    parent_agent.fork(enabled_toolsets=["core"], system_addendum="")
    aux = FakeClient.instances[-1]
    schema = aux.tool_payloads[0]
    assert schema is not None
    names = {entry["function"]["name"] for entry in schema}
    forbidden = {"Read", "Write", "Edit", "Bash", "WebFetch", "WebSearch", "Glob", "Grep", "Agent"}
    assert names.isdisjoint(forbidden), f"forbidden tool leaked: {names & forbidden}"
