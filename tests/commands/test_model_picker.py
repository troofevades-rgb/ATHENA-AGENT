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
    monkeypatch.setattr(
        mod,
        "_openrouter_models",
        lambda: {"openai/gpt-4o": True, "anthropic/claude-sonnet-4": True},
    )

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
    monkeypatch.setattr(mod, "_openrouter_models", lambda: {})

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
    monkeypatch.setattr(mod, "_openrouter_models", lambda: {"openai/gpt-4o": True})

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
    monkeypatch.setattr(mod, "_openrouter_models", lambda: {"openai/c": True})

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
    monkeypatch.setattr(mod, "_openrouter_models", lambda: {})

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
    monkeypatch.setattr(mod, "_openrouter_models", lambda: {})

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
    monkeypatch.setattr(mod, "_openrouter_models", lambda: {})

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
    monkeypatch.setattr(mod, "_openrouter_models", lambda: {"openai/gpt-4o": True})

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
    monkeypatch.setattr(mod, "_switch_model", lambda _a, name: captured.setdefault("name", name))

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

    monkeypatch.setattr(
        mod,
        "_OPENROUTER_CACHE",
        (mod.time.time(), {"cached/model": True}),
    )

    # If the fetch path fired, it'd try to read the pool. We block
    # the model module's pool alias to raise so the test can prove
    # the cache short-circuited the fetch (no exception bubbles).
    def _boom(*_a, **_kw):
        raise RuntimeError("should not have fetched")

    monkeypatch.setattr(mod, "_global_pool", _boom)

    assert mod._openrouter_models() == {"cached/model": True}


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

    assert mod._openrouter_models() == {}


def test_same_provider_switch_strips_routing_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Switching between two models on the SAME hosted provider
    (e.g. ``anthropic/A`` -> ``anthropic/B``) must still strip the
    routing prefix from ``agent.model``. Without the strip, the next
    API call sends ``anthropic/B`` as the wire model id and the
    upstream provider 404s.

    Pin for dogfood bug: ``/model anthropic/claude-sonnet-4-5`` ->
    ``/model anthropic/claude-opus-4-7`` left ``agent.model`` as
    ``anthropic/claude-opus-4-7`` and Anthropic returned
    ``model: anthropic/claude-opus-4-7 not_found_error``."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod.ui, "info", lambda *a, **kw: None)
    monkeypatch.setattr(mod.ui, "warn", lambda *a, **kw: None)

    agent = _agent("claude-sonnet-4-5", provider_name="anthropic")
    agent.cfg.providers = None
    mod._switch_model(agent, "anthropic/claude-opus-4-7")

    assert agent.model == "claude-opus-4-7"


def test_same_provider_switch_strips_openrouter_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same invariant on the openrouter -> openrouter path. Both
    Phase 2 picker labels are prefixed, and a redirect between two
    OpenRouter models must NOT leave ``openrouter/`` on the wire."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod.ui, "info", lambda *a, **kw: None)
    monkeypatch.setattr(mod.ui, "warn", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "_OPENROUTER_CACHE", None)

    agent = _agent("openai/gpt-4o", provider_name="openrouter")
    agent.cfg.providers = None
    mod._switch_model(agent, "openrouter/anthropic/claude-sonnet-4.6")

    assert agent.model == "anthropic/claude-sonnet-4.6"


# ---------------------------------------------------------------------------
# Tool-capability awareness (added after dogfood found hermes-4-405b
# 404'd on tool schemas)
# ---------------------------------------------------------------------------


def test_picker_marks_non_tool_openrouter_models(
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Models whose OpenRouter catalog entry doesn't list ``tools``
    in ``supported_parameters`` get a ``[no-tools]`` marker in the
    picker. Operators see at-a-glance which models 404 the moment
    they prompt -- the agent ships tool schemas every turn."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_ollama_models", lambda _a: [])
    monkeypatch.setattr(
        mod,
        "_openrouter_models",
        lambda: {
            "anthropic/claude-sonnet-4.6": True,
            "nousresearch/hermes-4-405b": False,
        },
    )

    mod.cmd_model(_agent(), "")

    def _is_row(p: str) -> bool:
        return (
            "models" not in p[:20].lower()
            and "/model" not in p
            and "no-tools" not in p[:25]  # filter the footer legend
        )

    claude_line = next(
        p for p in _captured_ui["print"] if "anthropic/claude-sonnet-4.6" in p and _is_row(p)
    )
    hermes_line = next(
        p for p in _captured_ui["print"] if "nousresearch/hermes-4-405b" in p and _is_row(p)
    )
    assert "no-tools" not in claude_line
    assert "no-tools" in hermes_line


def test_picker_renders_footer_explaining_no_tools_marker(
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A footer explains what the ``[no-tools]`` marker means so the
    operator knows it's a capability flag, not arbitrary decoration."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_ollama_models", lambda _a: ["any-local"])
    monkeypatch.setattr(mod, "_openrouter_models", lambda: {})

    mod.cmd_model(_agent(), "")
    combined = " ".join(_captured_ui["print"])
    assert "no-tools" in combined
    # Explanation must mention the 404 / agent-turn / tool-schema
    # consequence so operators learn the why, not just the what.
    assert "404" in combined or "schema" in combined.lower() or "agent" in combined.lower()


def test_switch_to_non_tool_openrouter_model_warns(
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the operator switches to an OpenRouter model whose
    cached catalog entry has supports_tools=False, ``ui.warn`` fires
    with a concrete suggestion list. This catches the dogfood case
    where the operator picked hermes-4-405b and got a cryptic 404
    on the next prompt."""
    import athena.commands.model as mod

    monkeypatch.setattr(
        mod,
        "_OPENROUTER_CACHE",
        (mod.time.time(), {"nousresearch/hermes-4-405b": False}),
    )

    captured: dict[str, str] = {}

    def _stub_resolve(name, cfg, pool):
        captured["name"] = name
        provider = SimpleNamespace(name="openrouter", close=lambda: None)
        # Resolver strips the openrouter/ prefix.
        return provider, name[len("openrouter/") :]

    monkeypatch.setattr(mod, "resolve_provider", _stub_resolve)
    monkeypatch.setattr(mod, "_route", lambda *_a, **_kw: "openrouter")

    agent = _agent("qwen2.5", provider_name="ollama")
    mod._switch_model(agent, "openrouter/nousresearch/hermes-4-405b")

    warns = " ".join(m for m in _captured_ui.get("warn", [])) if "warn" in _captured_ui else ""
    # The capture fixture wires info/error/print but not warn. Pull
    # warn from a direct patch.
    # The body below uses the fact that ui.warn calls aren't in
    # _captured_ui by default; check via a separate spy.


def test_switch_to_non_tool_model_emits_clear_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same path as above but pinned via a dedicated ui.warn spy
    -- the warn message must name the bare model AND point at
    concrete tool-capable alternatives."""
    import athena.commands.model as mod

    monkeypatch.setattr(
        mod,
        "_OPENROUTER_CACHE",
        (mod.time.time(), {"nousresearch/hermes-4-70b": False}),
    )

    warnings: list[str] = []
    monkeypatch.setattr(mod.ui, "warn", lambda msg, *a, **kw: warnings.append(str(msg)))
    monkeypatch.setattr(mod.ui, "info", lambda *a, **kw: None)

    def _stub_resolve(name, cfg, pool):
        provider = SimpleNamespace(name="openrouter", close=lambda: None)
        return provider, name[len("openrouter/") :]

    monkeypatch.setattr(mod, "resolve_provider", _stub_resolve)
    monkeypatch.setattr(mod, "_route", lambda *_a, **_kw: "openrouter")

    agent = _agent("qwen2.5", provider_name="ollama")
    mod._switch_model(agent, "openrouter/nousresearch/hermes-4-70b")

    assert warnings
    combined = " ".join(warnings).lower()
    assert "nousresearch/hermes-4-70b" in combined
    assert "tool" in combined
    # Suggested alternatives include at least one known-good model
    # so the operator can immediately pivot.
    assert "claude" in combined or "gpt-4o" in combined or "llama" in combined


def test_switch_to_tool_capable_model_does_not_warn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Switching to a known tool-capable model fires NO warning --
    quiet path so the warning means something when it does fire."""
    import athena.commands.model as mod

    monkeypatch.setattr(
        mod,
        "_OPENROUTER_CACHE",
        (mod.time.time(), {"openai/gpt-4o": True}),
    )

    warnings: list[str] = []
    monkeypatch.setattr(mod.ui, "warn", lambda msg, *a, **kw: warnings.append(str(msg)))
    monkeypatch.setattr(mod.ui, "info", lambda *a, **kw: None)

    def _stub_resolve(name, cfg, pool):
        provider = SimpleNamespace(name="openrouter", close=lambda: None)
        return provider, name[len("openrouter/") :]

    monkeypatch.setattr(mod, "resolve_provider", _stub_resolve)
    monkeypatch.setattr(mod, "_route", lambda *_a, **_kw: "openrouter")

    agent = _agent("qwen2.5", provider_name="ollama")
    mod._switch_model(agent, "openrouter/openai/gpt-4o")

    assert warnings == []


def test_switch_with_no_catalog_fetched_does_not_warn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the catalog hasn't been fetched yet (operator hasn't
    opened the picker and is switching by name from session start),
    we don't know whether the model supports tools. Treat that as
    "don't know, assume yes" so we don't spam an unjustified warning."""
    import athena.commands.model as mod

    monkeypatch.setattr(mod, "_OPENROUTER_CACHE", None)

    warnings: list[str] = []
    monkeypatch.setattr(mod.ui, "warn", lambda msg, *a, **kw: warnings.append(str(msg)))
    monkeypatch.setattr(mod.ui, "info", lambda *a, **kw: None)

    def _stub_resolve(name, cfg, pool):
        provider = SimpleNamespace(name="openrouter", close=lambda: None)
        return provider, name[len("openrouter/") :]

    monkeypatch.setattr(mod, "resolve_provider", _stub_resolve)
    monkeypatch.setattr(mod, "_route", lambda *_a, **_kw: "openrouter")

    agent = _agent("qwen2.5", provider_name="ollama")
    mod._switch_model(agent, "openrouter/some-unknown-model")

    assert warnings == []


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
