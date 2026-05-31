"""``/model`` picker -- inspired by Claude Code's ``/model`` UX.

Three behaviors:

  * Empty ``/model`` -- render the picker (numbered, grouped by
    provider).
  * Numeric ``/model N`` -- map the index back to the last-rendered
    entry and switch.
  * ``/model NAME`` -- the legacy path; routes through resolve_provider.

Pins lock the contract so a future refactor can't quietly break
indexing, drop a provider section, or regress the legacy NAME path.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture
def _captured_ui(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    import athena.commands.model as mod

    buckets: dict[str, list[str]] = {
        "info": [],
        "error": [],
        "print": [],
    }

    def _record(bucket: str):
        def _capture(msg: Any = "", *_a: Any, **_kw: Any) -> None:
            buckets[bucket].append(str(msg))

        return _capture

    monkeypatch.setattr(mod.ui, "info", _record("info"))
    monkeypatch.setattr(mod.ui, "error", _record("error"))
    monkeypatch.setattr(mod.ui.console, "print", _record("print"))
    return buckets


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch: pytest.MonkeyPatch):
    """Reset the module-level picker cache and OpenRouter catalog
    cache around every test so state from one test doesn't leak
    into another."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_LAST_PICKER", [], raising=False)
    monkeypatch.setattr(mod, "_OPENROUTER_CACHE", None, raising=False)
    yield


def _agent(model: str = "current-model", provider_name: str = "ollama") -> SimpleNamespace:
    """Stub agent with the attrs the picker reads."""
    provider = SimpleNamespace(
        name=provider_name,
        close=lambda: None,
        list_models=lambda: ["unused"],
    )
    return SimpleNamespace(
        model=model,
        provider=provider,
        cfg=SimpleNamespace(profile="default"),
        _owns_client=False,
    )


# ---------------------------------------------------------------------------
# Empty arg -- render picker
# ---------------------------------------------------------------------------


def test_empty_arg_renders_picker_with_models(
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/model`` with no args lists models grouped by provider.
    Each line is numbered 1..N so operators can ``/model N``."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_ollama_models", lambda _a: ["llama3.1:8b", "qwen2.5"])
    monkeypatch.setattr(mod, "_openrouter_models", lambda: ["openai/gpt-4o", "anthropic/claude-sonnet-4"])

    mod.cmd_model(_agent("qwen2.5"), "")

    combined = " ".join(_captured_ui["print"])
    # Provider section headers visible.
    assert "Ollama" in combined or "local" in combined.lower()
    assert "OpenRouter" in combined
    # All four models present.
    assert "llama3.1:8b" in combined
    assert "qwen2.5" in combined
    assert "openai/gpt-4o" in combined
    assert "anthropic/claude-sonnet-4" in combined
    # Switch instruction shown.
    assert "/model" in combined


def test_picker_marks_active_model(
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The currently-active model is marked (``*``) so the operator
    sees which one they're on without scanning for it."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_ollama_models", lambda _a: ["qwen2.5", "llama3.1"])
    monkeypatch.setattr(mod, "_openrouter_models", lambda: [])

    mod.cmd_model(_agent("qwen2.5"), "")

    # The line for qwen2.5 has the active marker; the line for
    # llama3.1 does not. Filter out the header line which also
    # mentions the active model in its "(current: ...)" suffix.
    def _is_row(p: str) -> bool:
        # Picker rows start with "  *" or "   " and an index;
        # the header starts with "[bold]models[/]" / "models".
        return "models" not in p[:20].lower() and "/model" not in p
    qwen_line = next(p for p in _captured_ui["print"] if "qwen2.5" in p and _is_row(p))
    llama_line = next(p for p in _captured_ui["print"] if "llama3.1" in p and _is_row(p))
    assert "*" in qwen_line
    assert "*" not in llama_line


def test_picker_recognizes_active_openrouter_model_without_prefix(
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenRouter entries are displayed with the bare vendor/model
    form (the section header already says "OpenRouter"), so the
    active marker must match by bare name too -- otherwise
    ``agent.model == "openai/gpt-4o"`` wouldn't get the marker."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_ollama_models", lambda _a: [])
    monkeypatch.setattr(mod, "_openrouter_models", lambda: ["openai/gpt-4o"])

    mod.cmd_model(_agent("openai/gpt-4o"), "")

    # Filter out the header line which mentions the active model
    # in its "(current: ...)" suffix.
    def _is_row(p: str) -> bool:
        return "models" not in p[:20].lower() and "/model" not in p
    line = next(p for p in _captured_ui["print"] if "openai/gpt-4o" in p and _is_row(p))
    assert "*" in line


def test_picker_caches_entries_for_index_resolution(
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After rendering, ``_LAST_PICKER`` holds the entries so
    ``/model N`` can look them up. Without this, picker indexing
    can't work."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_ollama_models", lambda _a: ["a", "b"])
    monkeypatch.setattr(mod, "_openrouter_models", lambda: ["openai/c"])

    mod.cmd_model(_agent(), "")

    assert len(mod._LAST_PICKER) == 3
    assert mod._LAST_PICKER[0].label == "a"
    assert mod._LAST_PICKER[1].label == "b"
    assert mod._LAST_PICKER[2].label == "openrouter/openai/c"


def test_empty_picker_errors(
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither provider available -> error pointing at both
    fixes (Ollama daemon, OpenRouter key)."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_ollama_models", lambda _a: [])
    monkeypatch.setattr(mod, "_openrouter_models", lambda: [])

    mod.cmd_model(_agent(), "")

    assert _captured_ui["error"]
    combined = " ".join(_captured_ui["error"])
    assert "Ollama" in combined or "ollama" in combined
    assert "OpenRouter" in combined or "openrouter" in combined


# ---------------------------------------------------------------------------
# Numeric arg -- picker index resolution
# ---------------------------------------------------------------------------


def test_numeric_arg_resolves_to_entry(
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/model 2`` after a picker render switches to the second
    entry. Verifies the index is 1-based and maps to the right label."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_ollama_models", lambda _a: ["alpha", "beta"])
    monkeypatch.setattr(mod, "_openrouter_models", lambda: [])

    captured: dict[str, str] = {}

    def _spy_switch(_agent, name: str) -> None:
        captured["name"] = name

    monkeypatch.setattr(mod, "_switch_model", _spy_switch)

    agent = _agent()
    mod.cmd_model(agent, "")  # render first to populate _LAST_PICKER
    mod.cmd_model(agent, "2")

    assert captured["name"] == "beta"


def test_numeric_arg_with_no_picker_errors(
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/model 3`` without first running ``/model`` errors clearly
    rather than silently doing nothing."""
    import athena.commands.model as mod

    mod.cmd_model(_agent(), "3")

    assert _captured_ui["error"]
    assert any("picker" in m.lower() for m in _captured_ui["error"])


def test_numeric_out_of_range_errors(
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Index beyond the rendered list errors with the valid range."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_ollama_models", lambda _a: ["only-one"])
    monkeypatch.setattr(mod, "_openrouter_models", lambda: [])

    agent = _agent()
    mod.cmd_model(agent, "")
    mod.cmd_model(agent, "99")

    assert _captured_ui["error"]
    assert any("99" in m for m in _captured_ui["error"])


def test_numeric_arg_resolves_to_openrouter_with_prefix(
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the picker entry is OpenRouter, ``/model N`` switches
    to the ``openrouter/<vendor/model>`` form -- the routable label,
    NOT the bare displayed name. Otherwise resolve_provider would
    route the vendor/model string to Ollama and fail."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_ollama_models", lambda _a: [])
    monkeypatch.setattr(mod, "_openrouter_models", lambda: ["openai/gpt-4o"])

    captured: dict[str, str] = {}

    def _spy_switch(_agent, name: str) -> None:
        captured["name"] = name

    monkeypatch.setattr(mod, "_switch_model", _spy_switch)

    agent = _agent()
    mod.cmd_model(agent, "")
    mod.cmd_model(agent, "1")

    assert captured["name"] == "openrouter/openai/gpt-4o"


# ---------------------------------------------------------------------------
# Name arg -- legacy path still works
# ---------------------------------------------------------------------------


def test_name_arg_calls_switch_directly(
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/model qwen2.5`` (legacy NAME path) routes through
    _switch_model without touching the picker. Verifies that
    existing operator habits keep working."""
    import athena.commands.model as mod

    captured: dict[str, str] = {}
    monkeypatch.setattr(
        mod, "_switch_model", lambda _a, name: captured.setdefault("name", name)
    )

    mod.cmd_model(_agent(), "qwen2.5")

    assert captured["name"] == "qwen2.5"


# ---------------------------------------------------------------------------
# OpenRouter catalog cache
# ---------------------------------------------------------------------------


def test_openrouter_cache_avoids_second_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_OPENROUTER_CACHE`` caches the catalog so a picker redraw
    doesn't re-hit the API. Pin the TTL behavior by setting cache
    state directly and confirming the fetch path doesn't fire."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_OPENROUTER_CACHE", (mod.time.time(), ["cached/model"]))

    # If the fetch path fired, it'd try to read the pool. We block
    # the model module's pool alias to raise so the test can prove
    # the cache short-circuited the fetch (no exception bubbles).
    def _boom(*_a, **_kw):
        raise RuntimeError("should not have fetched")

    monkeypatch.setattr(mod, "_global_pool", _boom)

    assert mod._openrouter_models() == ["cached/model"]


def test_openrouter_no_credential_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No openrouter key in pool -> empty list. The picker shows
    only Ollama models; no error fires (degraded gracefully).

    Patch the model module's local alias (``_global_pool``) rather
    than the canonical export -- the loader picked up the symbol
    at import time so that's the binding to override."""
    import athena.commands.model as mod

    class _EmptyPool:
        def get(self, name: str):
            return None

    monkeypatch.setattr(mod, "_global_pool", lambda: _EmptyPool())

    assert mod._openrouter_models() == []


def test_ollama_falls_back_to_fresh_when_active_provider_isnt_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the active provider is OpenRouter / Anthropic / etc.,
    the picker still needs to show local Ollama models. The
    fallback path constructs a fresh OllamaProvider."""
    import athena.commands.model as mod

    class _FreshOllama:
        def __init__(self):
            pass

        def list_models(self):
            return ["from-fresh"]

    monkeypatch.setattr("athena.providers.ollama.OllamaProvider", _FreshOllama)

    agent = SimpleNamespace(
        provider=SimpleNamespace(name="openrouter"),
        model="x",
        cfg=None,
    )
    assert mod._ollama_models(agent) == ["from-fresh"]
