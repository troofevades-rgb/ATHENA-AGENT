"""Parity baseline for ``supports_tools`` / ``supports_streaming`` (T5-01R.1).

The T5-01R retarget folds these two methods into the new
:class:`Capabilities` manifest. The contract that mustn't break:
**every currently-registered provider returns True for both,
independent of the model string**. This is the behaviour today
because the base :class:`Provider` defaults return True
unconditionally and no subclass overrides.

Run this BEFORE making any change to lock in the green baseline.
Re-run AFTER folding `supports_*` into `Capabilities` delegators
to prove no drift.
"""

from __future__ import annotations

import pytest

from athena.providers import get_provider_class, list_providers

# ctor builders, one per provider name. Each constructs the class
# with the minimum args its __init__ requires; no network fires at
# construction (each holds an httpx.Client config but doesn't connect).
_CTOR_FACTORIES: dict[str, callable] = {
    "ollama": lambda cls: cls(host="http://127.0.0.1:11434"),
    "anthropic": lambda cls: cls(api_key="sk-test"),
    "codex": lambda cls: cls(api_key="sk-test"),
    "openai": lambda cls: cls(api_key="sk-test"),
    "google": lambda cls: cls(api_key="key"),
    "openrouter": lambda cls: cls(api_key="key"),
    "nous": lambda cls: cls(api_key="key"),
    "xai": lambda cls: cls(api_key="key"),
    "openai_compat": lambda cls: cls(api_key=None, host="http://127.0.0.1:8000"),
    # T6-02: the social provider is a capability-only adapter
    # (declares social_search; not a chat backend). The
    # baseline supports_tools / supports_streaming parity is
    # checked separately below — exclude social from the
    # chat-backend parametrize.
    "social": lambda cls: cls(),
    # T6-05: stub_video_local is also capability-only
    # (declares video_generation). Same exclusion.
    "stub_video_local": lambda cls: cls(),
    # T6-05R: xai_video adapter — capability-only (video_generation),
    # not a chat backend. Constructor takes no args at the Provider
    # base level; key resolution happens lazily inside submit().
    "xai_video": lambda cls: cls(),
    # T4-04 / OCR: capability-only adapters registered lazily when
    # their respective subsystem modules are imported by other tests.
    # Not chat backends.
    "audio_whisper_local": lambda cls: cls(),
    "ocr_tesseract_local": lambda cls: cls(),
}

# Chat backends — the parity tests below skip non-chat providers.
_NON_CHAT_PROVIDERS: frozenset[str] = frozenset(
    {
        "social", "stub_video_local", "xai_video",
        "audio_whisper_local", "ocr_tesseract_local",
    }
)


def _construct_for_test(name: str):
    cls = get_provider_class(name)
    factory = _CTOR_FACTORIES.get(name)
    assert factory is not None, (
        f"no test ctor for provider {name!r}; add one to _CTOR_FACTORIES in test_supports_parity.py"
    )
    return factory(cls)


# ---------------------------------------------------------------------------
# Parity assertions — green before AND after the manifest fold
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list_providers())
def test_supports_tools_returns_true(name: str) -> None:
    """Baseline expectation: every CHAT provider returns True
    from supports_tools regardless of the model. Non-chat
    providers (capability-only adapters like social) are
    excluded — they honestly declare tool_calls=False."""
    if name in _NON_CHAT_PROVIDERS:
        pytest.skip(f"{name} is a capability-only provider, not a chat backend")
    p = _construct_for_test(name)
    try:
        assert p.supports_tools("any-model") is True
        # Try a few common model strings to make sure no override
        # silently flips behaviour based on the input.
        assert p.supports_tools("") is True
        assert p.supports_tools("gpt-4o") is True
    finally:
        try:
            p.close()
        except Exception:
            pass


@pytest.mark.parametrize("name", list_providers())
def test_supports_streaming_returns_true(name: str) -> None:
    """Same shape for supports_streaming."""
    if name in _NON_CHAT_PROVIDERS:
        pytest.skip(f"{name} is a capability-only provider, not a chat backend")
    p = _construct_for_test(name)
    try:
        assert p.supports_streaming("any-model") is True
        assert p.supports_streaming("") is True
        assert p.supports_streaming("claude-sonnet-4-6") is True
    finally:
        try:
            p.close()
        except Exception:
            pass


def test_all_registered_providers_have_a_ctor_factory() -> None:
    """Belt-and-braces: a future provider registration must
    explicitly add a ctor factory here. Without it, the parametrize
    above would silently skip that provider's parity check."""
    registered = set(list_providers())
    known = set(_CTOR_FACTORIES)
    missing = registered - known
    assert not missing, (
        f"providers in _REGISTRY but absent from the parity ctor "
        f"factory map: {sorted(missing)}. Add a factory."
    )
