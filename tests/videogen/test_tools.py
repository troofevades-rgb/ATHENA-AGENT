"""Backend-resolution + stub-backend tests (T6-05.2).

The job orchestrator + cost guard tests live in test_job.py /
test_cost_guard.py. This module covers:

  - Capabilities.video_generation field defaults + supports()
  - MediaRegistry.backend_for("video_generation") finds the
    registered backend
  - resolve_backend(cfg) returns an instance OR None
  - Local-preference is respected
  - Stub backend implements the full submit → poll → fetch
    contract end-to-end
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.providers.base import Capabilities, Provider
from athena.videogen import resolve_backend
from athena.videogen.backends.stub_local import StubLocalVideoBackend
from athena.videogen.job import (
    CostEstimate,
    GenerationRequest,
    JobHandle,
)


# ---------------------------------------------------------------------------
# Capability declaration
# ---------------------------------------------------------------------------


def test_capabilities_video_generation_defaults_false():
    """The conservative-default contract — only providers that
    explicitly declare video_generation are candidates."""
    c = Capabilities()
    assert c.video_generation is False
    assert c.supports("video_generation") is False


def test_capabilities_video_generation_when_declared():
    c = Capabilities(video_generation=True)
    assert c.video_generation is True
    assert c.supports("video_generation") is True


def test_stub_backend_declares_video_generation():
    """The stub provider registered at import time declares
    the capability — so the broker has something to resolve
    out-of-the-box."""
    caps = StubLocalVideoBackend.static_capabilities()
    assert caps.video_generation is True
    assert caps.is_local is True


# ---------------------------------------------------------------------------
# MediaRegistry resolution
# ---------------------------------------------------------------------------


def test_backend_resolved_via_broker():
    """best_provider_for({'video_generation'}) finds the
    stub backend after the providers module has imported it."""
    from athena.providers import best_provider_for

    name = best_provider_for({"video_generation"})
    assert name == "stub_video_local"


def test_no_backend_returns_unavailable(monkeypatch):
    """Empty registry → resolve_backend returns None cleanly,
    no crash. The caller surfaces a structured "not
    configured" payload."""
    monkeypatch.setattr("athena.providers._REGISTRY", {})
    monkeypatch.setattr("athena.media.registry._REGISTRY", {})

    cfg = SimpleNamespace(
        video_backend_prefer="local",
        media_backend_prefer="local",
    )
    assert resolve_backend(cfg) is None


def test_local_preferred_when_available(monkeypatch):
    """Default cfg → local-preferred → the stub_local backend
    wins over any hosted declarer.

    Set up two video_generation providers (one local, one
    hosted); resolve_backend should pick the local one."""
    from athena.providers.base import Capabilities as Caps

    class _HostedVideo(Provider):
        pass

    _HostedVideo.name = "hosted_video"
    _HostedVideo.requires_api_key = False
    _HostedVideo.static_capabilities = classmethod(
        lambda cls, model=None: Caps(video_generation=True, is_local=False)
    )  # type: ignore[method-assign]

    def _shim_stream_chat(self, *, model, messages, **kw):
        raise NotImplementedError

    def _shim_parse(self, content, raw_response):
        return content, []

    _HostedVideo.stream_chat = _shim_stream_chat  # type: ignore[method-assign]
    _HostedVideo.parse_tool_calls = _shim_parse  # type: ignore[method-assign]

    registry = {
        "stub_video_local": StubLocalVideoBackend,
        "hosted_video": _HostedVideo,
    }
    monkeypatch.setattr("athena.providers._REGISTRY", registry)
    monkeypatch.setattr("athena.media.registry._REGISTRY", registry)

    cfg = SimpleNamespace(
        video_backend_prefer="local",
        media_backend_prefer="local",
    )
    backend = resolve_backend(cfg)
    assert backend is not None
    assert backend.name == "stub_video_local"


def test_resolve_backend_missing_protocol_methods(monkeypatch):
    """A provider declaring video_generation but missing the
    protocol methods (estimate/submit/poll/fetch) → resolver
    returns None with a warning rather than handing back an
    instance that would crash on first use."""
    from athena.providers.base import Capabilities as Caps

    class _BadProvider(Provider):
        pass

    _BadProvider.name = "bad_video"
    _BadProvider.requires_api_key = False
    _BadProvider.static_capabilities = classmethod(
        lambda cls, model=None: Caps(video_generation=True, is_local=True)
    )  # type: ignore[method-assign]
    # NB no estimate/submit/poll/fetch.
    _BadProvider.stream_chat = lambda *a, **k: (_ for _ in ()).throw(NotImplementedError())  # type: ignore[method-assign]
    _BadProvider.parse_tool_calls = lambda self, c, r: (c, [])  # type: ignore[method-assign]

    monkeypatch.setattr(
        "athena.providers._REGISTRY", {"bad_video": _BadProvider}
    )
    monkeypatch.setattr(
        "athena.media.registry._REGISTRY", {"bad_video": _BadProvider}
    )

    cfg = SimpleNamespace(
        video_backend_prefer="local",
        media_backend_prefer="local",
    )
    assert resolve_backend(cfg) is None


# ---------------------------------------------------------------------------
# Stub backend end-to-end
# ---------------------------------------------------------------------------


def test_stub_backend_full_cycle(tmp_path: Path):
    """Verify the stub backend implements the full Protocol
    contract — estimate / submit / poll / fetch all do
    sensible things."""
    backend = StubLocalVideoBackend()
    request = GenerationRequest(
        mode="text_to_video", prompt="a stub clip", duration_s=4.0
    )

    est = backend.estimate(request)
    assert isinstance(est, CostEstimate)
    assert est.seconds_est == 4.0
    assert est.cost_est is None

    handle = backend.submit(request)
    assert isinstance(handle, JobHandle)
    assert handle.backend == "stub_video_local"
    assert handle.job_id.startswith("stub-")
    assert handle.status == "pending"

    polled = backend.poll(handle)
    assert polled.status == "done"
    assert polled.progress == 1.0

    out = backend.fetch(polled, out_dir=tmp_path)
    assert out.exists()
    assert out.suffix == ".mp4"
    assert b"ATHENA-STUB-VIDEO" in out.read_bytes()


def test_stub_backend_chat_methods_raise():
    """The stub backend is capability-only — chat methods
    raise. The chat-parity test in test_supports_parity.py
    already skips it via _NON_CHAT_PROVIDERS."""
    backend = StubLocalVideoBackend()
    with pytest.raises(NotImplementedError):
        # No actual call — just exercising stream_chat's
        # NotImplementedError path.
        backend.stream_chat(model="x", messages=[])
