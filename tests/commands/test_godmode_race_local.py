"""``/godmode race --tier ollama-local`` -- the athena-exclusive
zero-API-cost variant.

Phase 2 follow-up. Hermes-agent can't do this -- ULTRAPLINIAN there
is OpenRouter-only. Athena's provider abstraction lets us race the
operator's locally-pulled Ollama models with no API spend, using
the same scoring infrastructure as the OpenRouter tiers.

Pins:

  * ``--tier ollama-local`` resolves to the live agent's
    OllamaProvider when available, otherwise constructs a fresh one.
  * Models come from ``provider.list_models()`` (the
    ``/api/tags`` endpoint output) -- whatever's installed.
  * No models installed -> clear error pointing operators at
    ``ollama pull``.
  * Daemon not reachable -> clear error pointing operators at
    starting it.
  * OPENROUTER_API_KEY is NOT required for the local path -- it's
    only checked on the OpenRouter tiers.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _isolate_dotenv(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
):
    import athena.env as env_mod

    fake = tmp_path_factory.mktemp("dotenv_iso") / "missing.env"
    monkeypatch.setattr(env_mod, "_path", lambda: fake)
    env_mod.reset_cache()
    yield
    env_mod.reset_cache()


@pytest.fixture
def _gate_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATHENA_ALLOW_GODMODE", "1")


@pytest.fixture
def _captured_ui(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    import athena.commands.godmode as gm

    buckets: dict[str, list[str]] = {
        "warn": [],
        "error": [],
        "info": [],
        "print": [],
    }

    def _record(bucket: str):
        def _capture(msg: Any = "", *_a: Any, **_kw: Any) -> None:
            buckets[bucket].append(str(msg))

        return _capture

    monkeypatch.setattr(gm.ui, "warn", _record("warn"))
    monkeypatch.setattr(gm.ui, "error", _record("error"))
    monkeypatch.setattr(gm.ui, "info", _record("info"))
    monkeypatch.setattr(gm.ui.console, "print", _record("print"))
    return buckets


class _FakeOllamaProvider:
    """Stand-in for OllamaProvider. ``name`` is used by the
    ``getattr(provider, "name", "") == "ollama"`` branch in
    ``_resolve_race_provider_and_models``."""

    name = "ollama"

    def __init__(self, models: list[str] | None = None, raises: Exception | None = None):
        self._models = models or []
        self._raises = raises

    def list_models(self) -> list[str]:
        if self._raises is not None:
            raise self._raises
        return self._models


def _agent_with_ollama(models: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        workspace=None,
        cfg=SimpleNamespace(profile="default", model="qwen2.5"),
        session_id="sess-race-local",
        provider=_FakeOllamaProvider(models=models),
    )


# ---------------------------------------------------------------------------
# tier acceptance + provider resolution
# ---------------------------------------------------------------------------


def test_ollama_local_tier_is_accepted(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--tier ollama-local`` is part of _VALID_RACE_TIERS so the
    command doesn't reject it as an invalid tier name."""
    import athena.commands.godmode as gm
    import athena.jailbreak as jb

    captured: dict[str, Any] = {}

    def _spy(provider: Any, models: Any, *a: Any, **kw: Any) -> list[Any]:
        captured["provider"] = provider
        captured["models"] = list(models)
        return []

    monkeypatch.setattr(jb, "race_models", _spy)
    agent = _agent_with_ollama(models=["qwen2.5:latest", "llama3.1:8b"])
    gm.cmd_godmode(agent, "race what does X do --tier ollama-local")

    # No "unknown tier" error.
    assert not any("unknown tier" in m.lower() for m in _captured_ui["error"])
    assert captured["models"] == ["qwen2.5:latest", "llama3.1:8b"]


def test_ollama_local_uses_existing_ollama_provider(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``agent.provider`` is already an OllamaProvider, the
    racer reuses it rather than constructing a new one. This avoids
    duplicate connections and uses whatever host the live session
    is already pointing at."""
    import athena.commands.godmode as gm
    import athena.jailbreak as jb

    captured: dict[str, Any] = {}

    def _spy(provider: Any, *a: Any, **kw: Any) -> list[Any]:
        captured["provider"] = provider
        return []

    monkeypatch.setattr(jb, "race_models", _spy)
    fake_provider = _FakeOllamaProvider(models=["qwen2.5:latest"])
    agent = SimpleNamespace(
        workspace=None,
        cfg=SimpleNamespace(profile="default", model="x"),
        session_id="sess",
        provider=fake_provider,
    )
    gm.cmd_godmode(agent, "race anything --tier ollama-local")

    assert captured["provider"] is fake_provider


# ---------------------------------------------------------------------------
# error paths -- daemon down, no models, OPENROUTER_API_KEY irrelevant
# ---------------------------------------------------------------------------


def test_ollama_local_no_models_installed_errors(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
) -> None:
    """No installed models -> error pointing at ``ollama pull``.
    Avoids silently running an empty race."""
    from athena.commands.godmode import cmd_godmode

    agent = _agent_with_ollama(models=[])
    cmd_godmode(agent, "race anything --tier ollama-local")

    assert _captured_ui["error"]
    combined = " ".join(_captured_ui["error"])
    assert "ollama pull" in combined.lower() or "ollama pull" in combined


def test_ollama_local_daemon_down_errors(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
) -> None:
    """list_models raising (daemon down, network failure, etc.) ->
    error mentioning the daemon."""
    from athena.commands.godmode import cmd_godmode

    agent = SimpleNamespace(
        workspace=None,
        cfg=SimpleNamespace(profile="default", model="x"),
        session_id="sess",
        provider=_FakeOllamaProvider(raises=ConnectionError("connection refused")),
    )
    cmd_godmode(agent, "race anything --tier ollama-local")

    assert _captured_ui["error"]
    combined = " ".join(_captured_ui["error"]).lower()
    assert "ollama" in combined
    assert "daemon" in combined or "running" in combined


def test_ollama_local_does_not_require_openrouter_key(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The OPENROUTER_API_KEY check is bypassed for local racing
    -- operators on air-gapped / offline setups can still race."""
    import athena.commands.godmode as gm
    import athena.jailbreak as jb

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(jb, "race_models", lambda *a, **kw: [])

    agent = _agent_with_ollama(models=["qwen2.5:latest"])
    gm.cmd_godmode(agent, "race anything --tier ollama-local")

    assert not any(
        "OPENROUTER_API_KEY" in m for m in _captured_ui["error"]
    )
