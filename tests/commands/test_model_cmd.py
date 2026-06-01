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


# ---- typo guard: reject near-miss provider prefixes ------------------


def test_typo_in_provider_prefix_rejected_with_suggestion() -> None:
    """``/model athropic/claude-opus-4-7`` is a typo of ``anthropic/``.
    Without this guard, ``_route`` silently falls through to ollama
    (the local-first default) and the operator sees 404 errors on
    every subsequent turn -- the exact failure mode that surfaced
    this fix (dogfood burned 174 goal-loop turns hammering Ollama
    with the typo'd model name)."""
    agent = _fake_agent(model="qwen", provider_name="ollama")
    original_provider = agent.provider
    out = _run(agent, "athropic/claude-opus-4-7")
    assert agent.model == "qwen"  # unchanged
    assert agent.provider is original_provider  # unchanged
    assert "did you mean" in out.lower()
    assert "anthropic/claude-opus-4-7" in out


def test_typo_near_miss_openai_rejected() -> None:
    """``opena/gpt-4o`` is a near miss of ``openai/`` and should be
    caught the same way."""
    agent = _fake_agent(model="qwen", provider_name="ollama")
    out = _run(agent, "opena/gpt-4o")
    assert "did you mean" in out.lower()
    assert "openai/gpt-4o" in out


def test_legitimate_vendor_path_not_rejected() -> None:
    """Ollama tags often have the ``vendor/model`` shape
    (``mistralai/mistral-7b``, ``qwen/qwen3-32b``). Those share no
    meaningful letters with any provider prefix and must pass
    through the typo guard untouched."""
    agent = _fake_agent(model="qwen", provider_name="ollama")
    with (
        patch("athena.commands.model._route", return_value="ollama"),
        patch("athena.commands.model._bare_model", return_value="mistralai/mistral-7b"),
    ):
        out = _run(agent, "mistralai/mistral-7b")
    # No "did you mean" message; switch proceeded.
    assert "did you mean" not in out.lower()
    assert agent.model == "mistralai/mistral-7b"


# ---- leading-slash strip (dogfood paste / typo) ---------------------


def test_leading_slash_is_stripped_before_routing() -> None:
    """``/model /troofevades-q35:athena`` -- the operator pasted /
    typo'd a leading slash, which Ollama rejects as ``HTTP 400
    invalid model name``. The picker strips the slash and
    forwards the clean name. Surfaced after a dogfood session
    burned several turns with Ollama returning 400 on every
    prompt before the operator noticed."""
    agent = _fake_agent(model="qwen2.5-coder:14b", provider_name="ollama")
    with (
        patch("athena.commands.model._route", return_value="ollama"),
        patch(
            "athena.commands.model._bare_model",
            return_value="troofevades-q35:athena",
        ),
    ):
        out = _run(agent, "/troofevades-q35:athena")
    # Routed without the leading slash; agent.model is the clean name.
    assert agent.model == "troofevades-q35:athena"
    # No error about invalid model name.
    assert "invalid" not in out.lower()
    assert "model set to" in out.lower()


def test_only_slash_input_rejected_cleanly() -> None:
    """A bare ``/`` (or a string that's nothing but slashes) leaves
    nothing to route after the strip. Surface a clear error rather
    than silently calling resolve_provider with empty input."""
    agent = _fake_agent(model="qwen", provider_name="ollama")
    original_model = agent.model
    out = _run(agent, "/")
    # Model is unchanged.
    assert agent.model == original_model
    assert "empty" in out.lower() or "model name" in out.lower()


def test_known_provider_prefix_passes_through_typo_guard() -> None:
    """``anthropic/claude-opus`` is the canonical spelling and must
    NOT trip the typo guard."""
    from unittest.mock import MagicMock as _MM

    agent = _fake_agent(model="qwen", provider_name="ollama")
    new_provider = _MM()
    new_provider.name = "anthropic"
    with (
        patch("athena.commands.model._route", return_value="anthropic"),
        patch(
            "athena.commands.model.resolve_provider",
            return_value=(new_provider, "claude-opus"),
        ),
    ):
        out = _run(agent, "anthropic/claude-opus")
    assert "did you mean" not in out.lower()
    assert agent.model == "claude-opus"
