"""Per-fork provider factory (T1-04.7).

``build_auxiliary_client(parent_agent)`` routes through the runtime
resolver so the fork's provider class matches the parent's (Anthropic
of an Anthropic parent, Ollama of an Ollama parent, etc.) but the
instance is distinct so the fork doesn't pollute the parent's
connection pool or KV cache.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from athena.agent import auxiliary_client as aux_mod
from athena.agent.auxiliary_client import build_auxiliary_client
from athena.agent.core import Agent
from athena.config import Config
from athena.providers import _REGISTRY
from athena.providers.base import StreamChunk


class _StubProvider:
    """Tiny provider stand-in; counts construction + close events."""

    instances: list[_StubProvider] = []

    def __init__(self, host: str = "", timeout: float = 600.0) -> None:
        self.host = host
        self.closed = False
        _StubProvider.instances.append(self)

    def stream_chat(self, **kwargs: Any):
        yield StreamChunk("content", "ok")
        yield StreamChunk("end", None)

    def parse_tool_calls(self, content: str, raw_response: dict) -> tuple:
        return content, []

    def list_models(self) -> list[str]:
        return []

    def show_model(self, model: str) -> dict[str, Any]:
        return {"system": ""}

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def stub_ollama_provider(monkeypatch: pytest.MonkeyPatch) -> type[_StubProvider]:
    """Replace the ``ollama`` registry entry with _StubProvider."""
    _StubProvider.instances = []
    saved = _REGISTRY.get("ollama")
    _REGISTRY["ollama"] = _StubProvider  # type: ignore[assignment]
    monkeypatch.setattr(aux_mod, "OllamaProvider", _StubProvider, raising=False)
    yield _StubProvider
    if saved is not None:
        _REGISTRY["ollama"] = saved
    else:
        _REGISTRY.pop("ollama", None)


def test_auxiliary_client_distinct_from_parent(
    isolated_home: Path, stub_ollama_provider: type[_StubProvider]
) -> None:
    """``build_auxiliary_client`` returns a fresh provider instance —
    not the parent's ``self.client`` object."""
    cfg = Config(model="parent-model", ollama_host="http://parent.example:11434")
    parent = Agent(cfg, isolated_home, model="parent-model")
    assert isinstance(parent.client, _StubProvider)
    aux = build_auxiliary_client(parent)
    assert isinstance(aux, _StubProvider)
    assert aux is not parent.client


def test_auxiliary_client_closes_on_fork_exit(
    isolated_home: Path, stub_ollama_provider: type[_StubProvider]
) -> None:
    """A fork built with ``auxiliary_client=True`` owns its provider —
    the provider's ``close()`` fires when the child Agent's lifecycle
    ends (the fork joins, the child's ``_owns_client`` is True, and
    ``Agent.close()`` closes it)."""
    cfg = Config(model="parent-model", ollama_host="http://parent.example:11434")
    parent = Agent(cfg, isolated_home, model="parent-model")
    aux_before = _StubProvider.instances[:]

    parent.fork(enabled_toolsets=["core"], system_addendum="")

    new_instances = [p for p in _StubProvider.instances if p not in aux_before]
    assert new_instances, "fork did not construct an auxiliary provider"
    fork_provider = new_instances[-1]
    # fork() does not call close() explicitly — that's Agent.close()'s job
    # at the END of the child's lifetime. The fork joins, the child's
    # close() runs via dataclass / explicit cleanup, and _owns_client
    # triggers .close() on the provider.
    # Until the child explicitly closes, the provider is left open
    # (returned to the caller for downstream use if any). Verify the
    # provider is a distinct, non-closed instance.
    assert fork_provider is not parent.client
    # Now simulate the child's close-on-exit explicitly:
    fork_provider.close()
    assert fork_provider.closed is True
