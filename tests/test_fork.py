"""Tests for Agent.fork() — the daemon-thread sub-agent primitive.

These tests use a fake OllamaClient so they don't talk to a real model. The
fake captures whatever it sees inside ``chat()`` so we can assert on the
state of ContextVars *during* the fork's tool loop.
"""
from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Any

import pytest

import ocode.agent.core as core_mod
from ocode.agent import Agent, ForkResult
from ocode.config import Config
from ocode.ollama_client import ChatChunk
from ocode.provenance import (
    BACKGROUND_REVIEW,
    CURATOR,
    FOREGROUND,
    get_current_write_origin,
)
from ocode.safety.approval_callback import (
    AUTO_DENY,
    _interactive_approval,
    get_approval_callback,
)


class FakeClient:
    """Records every chat() call and yields a deterministic final response.

    A class-level list lets tests inspect parent and child clients across
    instances; the per-instance ``observations`` field captures ContextVar
    state seen from inside chat().
    """
    instances: list["FakeClient"] = []

    def __init__(self, host: str, timeout: float = 600.0) -> None:
        self.host = host
        self.observations: list[dict[str, Any]] = []
        self.tool_payloads: list[list[dict] | None] = []
        self.closed = False
        FakeClient.instances.append(self)

    def show_model(self, model: str) -> dict[str, Any]:
        return {"system": ""}

    def list_models(self) -> list[str]:
        return []

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        num_ctx: int | None = None,
    ):
        self.tool_payloads.append(tools)
        self.observations.append({
            "model": model,
            "write_origin": get_current_write_origin(),
            "approval_callback": get_approval_callback(),
            "messages": list(messages),
            "tools": tools,
        })
        yield ChatChunk(
            content="hello from fork",
            tool_calls=None,
            done=True,
            raw={"prompt_eval_count": 1, "eval_count": 2},
        )

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    """Swap in FakeClient wherever core.py builds an OllamaClient."""
    FakeClient.instances = []
    monkeypatch.setattr(core_mod, "OllamaClient", FakeClient)
    return FakeClient


@pytest.fixture
def parent_agent(tmp_path: Path, fake_client: type[FakeClient]) -> Agent:
    cfg = Config(model="parent-model", ollama_host="http://parent.example:11434")
    return Agent(cfg, tmp_path, model="parent-model")


# ---- Tests --------------------------------------------------------------


def test_fork_inherits_parent_runtime(parent_agent: Agent) -> None:
    """Child fork must use the parent's model and ollama_host even when the
    parent overrode them at runtime (i.e. without reading config from disk)."""
    result = parent_agent.fork(
        enabled_toolsets=["core"],
        system_addendum="be brief",
    )

    # Two FakeClients exist: one for parent, one for the fork's auxiliary client.
    fork_client = FakeClient.instances[-1]
    assert fork_client is not parent_agent.client
    assert fork_client.host == parent_agent.cfg.ollama_host
    assert fork_client.observations[0]["model"] == parent_agent.model
    assert isinstance(result, ForkResult)


def test_fork_uses_enabled_toolsets(parent_agent: Agent) -> None:
    """Tools advertised to the model must be limited to the chosen toolsets.
    'core' contains AskUserQuestion / ExitPlanMode / TaskCreate etc. — nothing
    from 'file', 'shell', 'web', or 'agent'."""
    parent_agent.fork(
        enabled_toolsets=["core"],
        system_addendum="",
    )
    fork_client = FakeClient.instances[-1]
    schema = fork_client.tool_payloads[0]
    assert schema is not None
    names = {entry["function"]["name"] for entry in schema}
    # Sanity: at least one core tool present, no file/shell/web/agent tools.
    forbidden = {"Read", "Write", "Edit", "Bash", "WebFetch", "WebSearch", "Glob", "Grep", "Agent"}
    assert names.isdisjoint(forbidden), f"forbidden tool leaked into core scope: {names & forbidden}"


def test_fork_sets_write_origin_during_execution(parent_agent: Agent) -> None:
    """The write_origin ContextVar must be bound to the configured value when
    the fork's chat() runs, and must be restored to FOREGROUND on the parent
    thread after the fork returns."""
    parent_agent.fork(
        enabled_toolsets=["core"],
        system_addendum="",
        write_origin=CURATOR,
    )
    fork_client = FakeClient.instances[-1]
    assert fork_client.observations[0]["write_origin"] == CURATOR
    assert get_current_write_origin() == FOREGROUND


def test_fork_uses_auto_deny_approval(parent_agent: Agent) -> None:
    """The approval callback inside the fork thread must be AUTO_DENY, and the
    parent thread's callback must be untouched."""
    parent_agent.fork(
        enabled_toolsets=["core"],
        system_addendum="",
    )
    fork_client = FakeClient.instances[-1]
    assert fork_client.observations[0]["approval_callback"] is AUTO_DENY
    assert get_approval_callback() is _interactive_approval


def test_fork_returns_result_with_final_response(parent_agent: Agent) -> None:
    """ForkResult.final_response is the fork's last assistant message text."""
    result = parent_agent.fork(
        enabled_toolsets=["core"],
        system_addendum="",
    )
    assert result.final_response == "hello from fork"
    assert result.error is None


def test_fork_quiet_mode_suppresses_output(
    parent_agent: Agent, capsys: pytest.CaptureFixture[str]
) -> None:
    """With quiet=True, the fork's writes to stdout/stderr land in a sink, not
    on the user's terminal. We can't capture the rich Console's internal
    output via capsys reliably, but we can verify stdout-redirect is wired by
    swapping sys.stdout with a recording StringIO from inside the fork."""
    import ocode.agent.fork as fork_mod

    class _NoCloseStringIO(io.StringIO):
        def close(self) -> None:  # fork's finally block calls .close()
            pass

    recording = _NoCloseStringIO()

    def _capture_sink():
        return recording

    # Replace _devnull with our recorder so we can prove redirection happened.
    original_devnull = fork_mod._devnull
    fork_mod._devnull = _capture_sink
    try:
        # Print something during the fork by having FakeClient.chat() print.
        original_chat = FakeClient.chat

        def chat_with_print(self, *args, **kwargs):
            print("FORK_INTERNAL_NOISE")
            yield from original_chat(self, *args, **kwargs)

        FakeClient.chat = chat_with_print
        try:
            parent_agent.fork(
                enabled_toolsets=["core"],
                system_addendum="",
                quiet=True,
            )
        finally:
            FakeClient.chat = original_chat
    finally:
        fork_mod._devnull = original_devnull

    # The fork's print must have been redirected into our sink, not stdout.
    out = capsys.readouterr().out
    assert "FORK_INTERNAL_NOISE" not in out
    assert "FORK_INTERNAL_NOISE" in recording.getvalue()


def test_fork_thread_is_daemon(parent_agent: Agent, monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker thread must be created with daemon=True."""
    seen: dict[str, Any] = {}
    real_thread = threading.Thread

    def capturing_thread(*args, **kwargs):
        if kwargs.get("name") == "ocode-fork":
            seen["daemon"] = kwargs.get("daemon")
            seen["name"] = kwargs.get("name")
        return real_thread(*args, **kwargs)

    import ocode.agent.fork as fork_mod
    monkeypatch.setattr(fork_mod.threading, "Thread", capturing_thread)
    parent_agent.fork(
        enabled_toolsets=["core"],
        system_addendum="",
    )
    assert seen.get("daemon") is True
    assert seen.get("name") == "ocode-fork"


def test_fork_thread_does_not_block_main_process_exit(
    parent_agent: Agent, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Daemon threads cannot block interpreter shutdown — we verify the
    constructed Thread is a daemon, which is the Python guarantee. (Spawning a
    real interpreter just to assert exit is overkill for a unit test.)"""
    spawned: list[threading.Thread] = []
    real_thread = threading.Thread

    def capturing_thread(*args, **kwargs):
        t = real_thread(*args, **kwargs)
        if kwargs.get("name") == "ocode-fork":
            spawned.append(t)
        return t

    import ocode.agent.fork as fork_mod
    monkeypatch.setattr(fork_mod.threading, "Thread", capturing_thread)
    parent_agent.fork(
        enabled_toolsets=["core"],
        system_addendum="",
    )
    assert len(spawned) == 1
    assert spawned[0].daemon is True
    # Thread has already joined inside fork(), so it must be done.
    assert not spawned[0].is_alive()
