"""Factory routes config to the right backend implementation."""

from __future__ import annotations

import asyncio

import pytest

from athena.config import Config, UserModelConfig
from athena.user_model import get_user_model_backend
from athena.user_model.markdown import MarkdownUserModel


def test_markdown_is_default():
    cfg = Config()
    backend = get_user_model_backend(cfg)
    assert isinstance(backend, MarkdownUserModel)


def test_none_returns_disabled_sentinel():
    cfg = Config(user_model=UserModelConfig(backend="none"))
    backend = get_user_model_backend(cfg)
    # Disabled backend is internal — duck-type via behavior.
    h = backend.health()
    assert h.status == "ready"
    assert h.backend == "none"
    # ingest should be a no-op
    result = asyncio.run(backend.ingest_session([], session_id="x"))
    assert result.facts_added == 0
    assert result.backend == "none"


def test_unknown_backend_raises_valueerror():
    cfg = Config(user_model=UserModelConfig(backend="quantum-honcho"))
    with pytest.raises(ValueError, match="unknown user_model backend"):
        get_user_model_backend(cfg)


def test_honcho_raises_not_implemented_for_now():
    """Until the Honcho adapter lands, picking it should raise
    a clear NotImplementedError pointing at the fallback."""
    cfg = Config(user_model=UserModelConfig(backend="honcho"))
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        get_user_model_backend(cfg)


def test_factory_accepts_no_llm_call(tmp_path):
    """The factory must be importable / callable without an LLM
    — config validation paths shouldn't need to construct a
    provider just to confirm the backend resolves."""
    cfg = Config()
    backend = get_user_model_backend(cfg, llm_call=None)
    # Calling .health() should still work (filesystem-only).
    assert backend.health().status == "ready"
