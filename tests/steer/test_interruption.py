"""/steer slash command + Agent steer-drain integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.commands import get_command
from athena.steer.queue import GLOBAL_STEER_QUEUE


class _FakeAgent:
    """Just enough surface for the steer command's contract."""

    def __init__(self, session_id: str = "test-session"):
        self.session_id = session_id


@pytest.fixture(autouse=True)
def _clear_global_queue():
    """Every test starts with an empty global queue."""
    GLOBAL_STEER_QUEUE.clear("test-session")
    GLOBAL_STEER_QUEUE.clear("agent-injection-session")
    yield
    GLOBAL_STEER_QUEUE.clear("test-session")
    GLOBAL_STEER_QUEUE.clear("agent-injection-session")


def test_steer_command_pushes_to_queue():
    cmd = get_command("steer")
    assert cmd is not None
    cmd(_FakeAgent(), "focus on tests")
    assert GLOBAL_STEER_QUEUE.list("test-session") == ["focus on tests"]


def test_steer_command_empty_arg_errors():
    cmd = get_command("steer")
    cmd(_FakeAgent(), "")
    # Still empty:
    assert GLOBAL_STEER_QUEUE.list("test-session") == []


def test_steer_command_clear():
    cmd = get_command("steer")
    cmd(_FakeAgent(), "a")
    cmd(_FakeAgent(), "b")
    assert len(GLOBAL_STEER_QUEUE.list("test-session")) == 2
    cmd(_FakeAgent(), "clear")
    assert GLOBAL_STEER_QUEUE.list("test-session") == []


def test_queue_command_lists_pending():
    """The /queue command snapshots the queue without consuming."""
    steer_cmd = get_command("steer")
    queue_cmd = get_command("queue")
    assert queue_cmd is not None
    steer_cmd(_FakeAgent(), "first")
    steer_cmd(_FakeAgent(), "second")
    queue_cmd(_FakeAgent(), "")
    # Items are still there after /queue.
    assert GLOBAL_STEER_QUEUE.list("test-session") == ["first", "second"]


def test_agent_pops_steer_before_user_prompt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Agent._inject_pending_steers drains the queue and appends synthetic
    user messages before the actual user prompt lands in history."""
    # Build a minimal Agent and exercise _inject_pending_steers directly.
    # Avoid spinning Ollama: we never invoke the chat loop.
    from athena.agent import Agent
    from athena.config import Config

    # Patch OllamaProvider so Agent.__init__ doesn't try a real HTTP call.
    class _NullClient:
        def __init__(self, *a, **k):
            pass

        def list_models(self):
            return []

        def show_model(self, model):
            return {}

        def stream_chat(self, *, model, messages, tools=None, **kwargs):
            if False:
                yield

        def close(self):
            pass

    import athena.agent.core as core_mod
    from athena.providers import _REGISTRY

    monkeypatch.setattr(core_mod, "OllamaProvider", _NullClient, raising=False)
    monkeypatch.setitem(_REGISTRY, "ollama", _NullClient)

    # Isolate ~/.athena so SessionStore writes go to tmp_path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    cfg = Config(profile="")  # disable session store
    agent = Agent(cfg, tmp_path)
    # Force a known session_id so we can drive the queue:
    agent.session_id = "agent-injection-session"

    # Push two steers:
    GLOBAL_STEER_QUEUE.push("agent-injection-session", "focus on tests")
    GLOBAL_STEER_QUEUE.push("agent-injection-session", "then commit")

    initial_msg_count = len(agent.messages)
    agent._inject_pending_steers()

    new_msgs = agent.messages[initial_msg_count:]
    assert len(new_msgs) == 2
    assert new_msgs[0] == {"role": "user", "content": "[/steer] focus on tests"}
    assert new_msgs[1] == {"role": "user", "content": "[/steer] then commit"}
    # Queue was drained:
    assert GLOBAL_STEER_QUEUE.list("agent-injection-session") == []


def test_agent_handles_empty_queue_silently(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No steers pending → _inject_pending_steers is a no-op."""
    from athena.agent import Agent
    from athena.config import Config

    class _NullClient:
        def __init__(self, *a, **k):
            pass

        def list_models(self):
            return []

        def show_model(self, m):
            return {}

        def stream_chat(self, *, model, messages, tools=None, **kwargs):
            if False:
                yield

        def close(self):
            pass

    import athena.agent.core as core_mod
    from athena.providers import _REGISTRY

    monkeypatch.setattr(core_mod, "OllamaProvider", _NullClient, raising=False)
    monkeypatch.setitem(_REGISTRY, "ollama", _NullClient)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    cfg = Config(profile="")
    agent = Agent(cfg, tmp_path)
    agent.session_id = "empty-queue-session"
    initial = len(agent.messages)
    agent._inject_pending_steers()
    assert len(agent.messages) == initial
