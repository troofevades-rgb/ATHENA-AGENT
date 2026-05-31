"""Tests for ``/model [NAME]`` — show or switch the active model.

The switch path is delicate: when the new model routes to a
DIFFERENT provider, the agent's provider object is replaced
wholesale via ``resolve_provider``. When it routes to the SAME
provider, only ``agent.model`` is swapped.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from athena.commands.model import cmd_model


def _capture():
    lines: list[str] = []
    patches = []
    for fn in ("info", "warn", "error"):
        patches.append(
            patch(
                f"athena.commands.model.ui.{fn}",
                side_effect=lambda msg, *a, _n=fn, **kw: lines.append(f"{_n}: {msg}"),
            )
        )
    return lines, patches


def _run(agent, arg: str) -> str:
    lines, patches = _capture()
    for p in patches:
        p.start()
    try:
        cmd_model(agent, arg)
    finally:
        for p in patches:
            p.stop()
    return "\n".join(lines)


def _fake_agent(model: str = "qwen", provider_name: str = "ollama"):
    return SimpleNamespace(
        model=model,
        cfg=SimpleNamespace(),
        provider=SimpleNamespace(name=provider_name, close=lambda: None),
        client=None,
        _owns_client=False,
    )


# ---- no arg: show current --------------------------------------------


def test_no_arg_renders_picker(monkeypatch) -> None:
    """``/model`` (no args) now renders the multi-provider picker
    instead of just printing the current name. The picker still
    shows the current model (with a ``*`` marker), so the bare
    name is still visible. No agent mutation.

    Captures ``ui.console.print`` directly because the picker
    writes through Rich's console, not ``ui.info`` like the legacy
    path did. The shared ``_run`` helper only sees the info/warn/
    error channels."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_ollama_models", lambda _a: ["qwen2.5-coder:14b"])
    monkeypatch.setattr(mod, "_openrouter_models", lambda: {})

    printed: list[str] = []
    monkeypatch.setattr(
        mod.ui.console, "print", lambda msg="", *a, **kw: printed.append(str(msg))
    )

    agent = _fake_agent(model="qwen2.5-coder:14b")
    mod.cmd_model(agent, "")
    out = "\n".join(printed)

    assert "qwen2.5-coder:14b" in out
    # Picker header + switch instruction visible.
    assert "models" in out.lower()
    assert "/model" in out
    # No mutation.
    assert agent.model == "qwen2.5-coder:14b"


# ---- swap within same provider --------------------------------------


def test_swap_within_same_provider_only_changes_model_name() -> None:
    """If the route resolves to the same provider, only the model
    name swaps — no provider object is rebuilt."""
    agent = _fake_agent(model="qwen", provider_name="ollama")
    original_provider = agent.provider
    with patch(
        "athena.commands.model._route",
        return_value="ollama",
    ):
        out = _run(agent, "llama3.2:3b")
    assert agent.model == "llama3.2:3b"
    # Provider object NOT replaced
    assert agent.provider is original_provider
    assert "model set to llama3.2:3b" in out.lower()


def test_swap_strips_whitespace_from_name() -> None:
    agent = _fake_agent(model="qwen", provider_name="ollama")
    with patch("athena.commands.model._route", return_value="ollama"):
        _run(agent, "  llama3.2:3b  ")
    assert agent.model == "llama3.2:3b"


# ---- swap across providers ------------------------------------------


def test_swap_across_providers_replaces_provider_object() -> None:
    """A cross-provider switch must rebuild the provider via
    resolve_provider and update agent.provider, agent.client,
    agent._owns_client, agent.model."""
    agent = _fake_agent(model="qwen", provider_name="ollama")
    new_provider = SimpleNamespace(name="anthropic", close=lambda: None)

    with (
        patch("athena.commands.model._route", return_value="anthropic"),
        patch(
            "athena.commands.model.resolve_provider",
            return_value=(new_provider, "claude-opus-4"),
        ),
    ):
        out = _run(agent, "anthropic/claude-opus-4")
    assert agent.provider is new_provider
    assert agent.client is new_provider
    assert agent._owns_client is True
    assert agent.model == "claude-opus-4"
    # Surfaced to user
    assert "anthropic/claude-opus-4" in out
    assert "ollama" in out
    assert "anthropic" in out


def test_swap_across_providers_closes_owned_client() -> None:
    """When agent owns the current provider's client, the swap
    must close it to release sockets/file handles."""
    closed: list[str] = []
    agent = _fake_agent(model="qwen", provider_name="ollama")
    agent.provider = SimpleNamespace(
        name="ollama",
        close=lambda: closed.append("old-closed"),
    )
    agent._owns_client = True
    new_provider = SimpleNamespace(name="anthropic", close=lambda: None)

    with (
        patch("athena.commands.model._route", return_value="anthropic"),
        patch(
            "athena.commands.model.resolve_provider",
            return_value=(new_provider, "claude-opus-4"),
        ),
    ):
        _run(agent, "anthropic/claude-opus-4")
    assert closed == ["old-closed"]


def test_swap_across_providers_skips_close_when_not_owner() -> None:
    """When the agent does NOT own the current client (a shared
    pooled provider, say), the swap must NOT close it."""
    closed: list[str] = []
    agent = _fake_agent(model="qwen", provider_name="ollama")
    agent.provider = SimpleNamespace(
        name="ollama",
        close=lambda: closed.append("should-not-fire"),
    )
    agent._owns_client = False
    new_provider = SimpleNamespace(name="anthropic", close=lambda: None)
    with (
        patch("athena.commands.model._route", return_value="anthropic"),
        patch(
            "athena.commands.model.resolve_provider",
            return_value=(new_provider, "claude"),
        ),
    ):
        _run(agent, "anthropic/claude")
    assert closed == []


def test_close_failure_during_swap_is_swallowed() -> None:
    """Closing the old client must never block the swap — if .close()
    raises, the swap still completes."""
    agent = _fake_agent(model="qwen", provider_name="ollama")

    def _raising_close():
        raise OSError("socket already gone")

    agent.provider = SimpleNamespace(name="ollama", close=_raising_close)
    agent._owns_client = True
    new_provider = SimpleNamespace(name="anthropic", close=lambda: None)
    with (
        patch("athena.commands.model._route", return_value="anthropic"),
        patch(
            "athena.commands.model.resolve_provider",
            return_value=(new_provider, "claude"),
        ),
    ):
        # Must not raise.
        _run(agent, "anthropic/claude")
    # Swap completed despite close error
    assert agent.provider is new_provider


def test_swap_resolve_failure_surfaces_error_and_leaves_state() -> None:
    """If resolve_provider raises (bad model name, no credential),
    the user sees a friendly error and the agent stays on the old
    provider."""
    agent = _fake_agent(model="qwen", provider_name="ollama")
    original_provider = agent.provider
    with (
        patch("athena.commands.model._route", return_value="anthropic"),
        patch(
            "athena.commands.model.resolve_provider",
            side_effect=ValueError("no ATHENA_ANTHROPIC_API_KEY in ~/.athena/.env"),
        ),
    ):
        out = _run(agent, "anthropic/claude")
    assert agent.model == "qwen"  # unchanged
    assert agent.provider is original_provider  # unchanged
    assert "could not switch" in out.lower()
    assert "no athena_anthropic_api_key" in out.lower()
