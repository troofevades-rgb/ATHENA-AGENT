"""Tests for the xAI Grok Imagine video backend.

Network is stubbed via monkeypatched ``urllib.request.urlopen`` — the
adapter goes through urllib to keep the base install dependency-free,
so all HTTP interactions are interceptable at one well-known spot.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from athena.videogen import job as job_mod
from athena.videogen.backends.xai import (
    XAIAPIError,
    XAIVideoBackend,
    _estimate_seconds,
    _resolution_for_xai,
    _resolve_api_key,
)


@pytest.fixture
def with_api_key(monkeypatch, tmp_path):
    """Drop a key into a fake .env so _resolve_api_key returns it."""
    from athena import env as env_mod

    fake_env = tmp_path / ".env"
    fake_env.write_text("ATHENA_XAI_API_KEY=xai-test-12345\n", encoding="utf-8")
    monkeypatch.setattr(env_mod, "_path", lambda: fake_env)
    env_mod.reset_cache()
    return "xai-test-12345"


@pytest.fixture
def no_api_key(monkeypatch, tmp_path):
    from athena import env as env_mod

    fake_env = tmp_path / ".env"
    monkeypatch.setattr(env_mod, "_path", lambda: fake_env)
    monkeypatch.delenv("ATHENA_XAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    env_mod.reset_cache()


# ----------------------------------------------------------------------
# Registration + capabilities
# ----------------------------------------------------------------------


def test_backend_registered_under_xai_video():
    import athena.providers  # noqa: F401 — populates registry

    from athena.providers import get_provider_class

    cls = get_provider_class("xai_video")
    assert cls is XAIVideoBackend


def test_capabilities_declare_video_generation():
    caps = XAIVideoBackend.static_capabilities()
    assert caps.supports("video_generation")
    assert not caps.is_local
    assert XAIVideoBackend.requires_api_key is True


def test_chat_methods_raise():
    """Capability-only — chat must error explicitly so the broker
    doesn't accidentally route conversation here."""
    backend = XAIVideoBackend()
    with pytest.raises(NotImplementedError):
        backend.stream_chat(model="grok", messages=[])


# ----------------------------------------------------------------------
# Estimate
# ----------------------------------------------------------------------


def test_estimate_floors_at_30s():
    """Very short clips still take 30s due to queue + render
    pipeline latency — don't pretend they return in 2s."""
    assert _estimate_seconds(2.0) == 30.0


def test_estimate_scales_4x_for_longer_clips():
    assert _estimate_seconds(15.0) == 60.0


def test_estimate_returns_no_cost():
    """xAI per-second pricing isn't publicly documented yet — cost
    stays None and the seconds threshold guards the operator."""
    req = job_mod.GenerationRequest(mode="text_to_video", prompt="x", duration_s=5.0)
    est = XAIVideoBackend().estimate(req)
    assert est.cost_est is None
    assert est.seconds_est >= 30.0


# ----------------------------------------------------------------------
# Aspect mapping
# ----------------------------------------------------------------------


def test_resolution_for_xai_default_is_720p():
    """xAI's API rejects pixel-dim strings (HTTP 422); the resolution
    field is a quality tier — 480p / 720p / 1080p."""
    assert _resolution_for_xai() == "720p"
    assert _resolution_for_xai(None) == "720p"


def test_resolution_for_xai_accepts_valid_quality_tiers():
    assert _resolution_for_xai("480p") == "480p"
    assert _resolution_for_xai("720p") == "720p"
    assert _resolution_for_xai("1080p") == "1080p"


def test_resolution_for_xai_falls_back_for_pixel_dims_or_garbage():
    """Legacy pixel-dim strings or unknown values fall to the default."""
    assert _resolution_for_xai("1280x720") == "720p"
    assert _resolution_for_xai("4k") == "720p"
    assert _resolution_for_xai("") == "720p"


# ----------------------------------------------------------------------
# API key resolution
# ----------------------------------------------------------------------


def test_resolve_api_key_from_dotenv(with_api_key):
    assert _resolve_api_key() == with_api_key


def test_resolve_api_key_falls_back_to_xai_canonical_name(monkeypatch, tmp_path):
    """xAI's own docs use XAI_API_KEY — accept that too."""
    from athena import env as env_mod

    fake_env = tmp_path / ".env"
    monkeypatch.setattr(env_mod, "_path", lambda: fake_env)
    monkeypatch.delenv("ATHENA_XAI_API_KEY", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-canonical")
    env_mod.reset_cache()
    assert _resolve_api_key() == "xai-canonical"


def test_resolve_api_key_returns_none_when_missing(no_api_key):
    assert _resolve_api_key() is None


# ----------------------------------------------------------------------
# Submit — HTTP stubbed
# ----------------------------------------------------------------------


def _fake_urlopen_response(payload: dict, status: int = 200):
    """Build a context-manager that mimics urllib's response shape."""
    body = json.dumps(payload).encode("utf-8")

    class _Resp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return body
        def getcode(self):
            return status

    return _Resp()


def test_submit_missing_key_raises(no_api_key):
    backend = XAIVideoBackend()
    req = job_mod.GenerationRequest(mode="text_to_video", prompt="x")
    with pytest.raises(XAIAPIError, match="no API key"):
        backend.submit(req)


def test_submit_rejects_image_to_video(with_api_key):
    """xAI's documented surface is text-to-video only; image-to-video
    needs to error clearly, not silently send the wrong shape."""
    backend = XAIVideoBackend()
    req = job_mod.GenerationRequest(
        mode="image_to_video", prompt="x", image_path=Path("/tmp/x.png"),
    )
    with pytest.raises(XAIAPIError, match="text_to_video"):
        backend.submit(req)


def test_submit_posts_expected_body(monkeypatch, with_api_key):
    """Pin the request body shape against the documented xAI contract."""
    captured: dict = {}

    def _fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8")) if req.data else None
        return _fake_urlopen_response(
            {"request_id": "req-abc123", "status": "pending"}
        )

    monkeypatch.setattr(
        "athena.videogen.backends.xai.urllib.request.urlopen", _fake_urlopen,
    )

    req = job_mod.GenerationRequest(
        mode="text_to_video", prompt="a sunrise", duration_s=5.0, aspect="16:9",
    )
    handle = XAIVideoBackend().submit(req)

    assert captured["url"] == "https://api.x.ai/v1/videos/generations"
    assert captured["method"] == "POST"
    # Authorization header carries the bearer token.
    auth = captured["headers"].get("Authorization", "")
    assert auth.startswith("Bearer xai-test-")
    # Body matches the documented field shape. xAI requires
    # ``duration`` as an int (HTTP 422 otherwise) — pin both the
    # value AND the type so a future float-cast regression breaks
    # tests instead of production.
    body = captured["body"]
    assert body["model"] == "grok-imagine-video"
    assert body["prompt"] == "a sunrise"
    assert body["duration"] == 5
    assert isinstance(body["duration"], int)
    assert body["aspect_ratio"] == "16:9"
    # xAI's API rejected pixel-dim strings like "1280x720" (HTTP 422);
    # resolution is a quality tier. Default is 720p.
    assert body["resolution"] == "720p"
    # Handle carries the request_id back.
    assert handle.job_id == "req-abc123"
    assert handle.status == "pending"
    assert handle.backend == "xai_video"


@pytest.mark.parametrize(
    "duration_s,expected",
    [
        (5.0, 5),
        (5, 5),
        (5.5, 6),       # round up
        (5.4, 5),       # round down
        (0.3, 1),       # min-1 floor
        (0, 1),         # min-1 floor
        (-2.0, 1),      # negative clamped to 1
    ],
)
def test_submit_duration_serializes_as_int(
    monkeypatch, with_api_key, duration_s, expected,
):
    """xAI rejects floats for the ``duration`` field with HTTP 422.
    The adapter rounds half-up to int and floors at 1."""
    captured: dict = {}

    def _fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _fake_urlopen_response({"request_id": "req-x"})

    monkeypatch.setattr(
        "athena.videogen.backends.xai.urllib.request.urlopen", _fake_urlopen,
    )

    req = job_mod.GenerationRequest(
        mode="text_to_video", prompt="x", duration_s=duration_s,
    )
    XAIVideoBackend().submit(req)
    assert captured["body"]["duration"] == expected
    assert isinstance(captured["body"]["duration"], int)


def test_submit_no_request_id_raises(monkeypatch, with_api_key):
    def _fake_urlopen(req, timeout=None):
        return _fake_urlopen_response({"status": "pending"})  # missing request_id

    monkeypatch.setattr(
        "athena.videogen.backends.xai.urllib.request.urlopen", _fake_urlopen,
    )
    backend = XAIVideoBackend()
    req = job_mod.GenerationRequest(mode="text_to_video", prompt="x")
    with pytest.raises(XAIAPIError, match="no request_id"):
        backend.submit(req)


# ----------------------------------------------------------------------
# Poll — status mapping
# ----------------------------------------------------------------------


def _stub_poll_response(monkeypatch, payload):
    def _fake_urlopen(req, timeout=None):
        return _fake_urlopen_response(payload)
    monkeypatch.setattr(
        "athena.videogen.backends.xai.urllib.request.urlopen", _fake_urlopen,
    )


def test_poll_done_flips_status_and_stashes_response(monkeypatch, with_api_key):
    _stub_poll_response(monkeypatch, {
        "status": "done",
        "video": {"url": "https://example.com/video.mp4"},
    })
    handle = job_mod.JobHandle(backend="xai_video", job_id="req-1", status="pending")
    out = XAIVideoBackend().poll(handle)
    assert out.status == "done"
    assert out.progress == 1.0
    assert out.extra["poll_response"]["video"]["url"] == "https://example.com/video.mp4"


def test_poll_failed_flips_status(monkeypatch, with_api_key):
    _stub_poll_response(monkeypatch, {"status": "failed", "error": "content policy"})
    handle = job_mod.JobHandle(backend="xai_video", job_id="req-1", status="pending")
    out = XAIVideoBackend().poll(handle)
    assert out.status == "failed"
    assert "content policy" in (out.error or "")


def test_poll_processing_marks_running(monkeypatch, with_api_key):
    _stub_poll_response(monkeypatch, {"status": "processing"})
    handle = job_mod.JobHandle(backend="xai_video", job_id="req-1", status="pending")
    out = XAIVideoBackend().poll(handle)
    assert out.status == "running"
    assert out.progress >= 0.5


def test_poll_unknown_status_keeps_current(monkeypatch, with_api_key):
    _stub_poll_response(monkeypatch, {"status": "queued_v2"})  # unrecognised
    handle = job_mod.JobHandle(
        backend="xai_video", job_id="req-1", status="pending", progress=0.0,
    )
    out = XAIVideoBackend().poll(handle)
    assert out.status == "pending"


def test_poll_network_failure_is_not_terminal(monkeypatch, with_api_key):
    """Transient HTTP failures should leave the handle in its current
    state with the error in `extra` — the orchestrator decides whether
    to keep polling. Marking 'failed' on every blip would tank long jobs."""
    def _raise(req, timeout=None):
        raise urllib_error_for_test()
    monkeypatch.setattr(
        "athena.videogen.backends.xai.urllib.request.urlopen", _raise,
    )
    handle = job_mod.JobHandle(backend="xai_video", job_id="req-1", status="running")
    out = XAIVideoBackend().poll(handle)
    assert out.status == "running"
    assert "last_poll_error" in out.extra


def urllib_error_for_test():
    import urllib.error
    return urllib.error.URLError("simulated transient")


# ----------------------------------------------------------------------
# Fetch — downloads .video.url to disk
# ----------------------------------------------------------------------


def test_fetch_requires_done_status(tmp_path):
    handle = job_mod.JobHandle(backend="xai_video", job_id="req-1", status="running")
    with pytest.raises(XAIAPIError, match="status='running'"):
        XAIVideoBackend().fetch(handle, out_dir=tmp_path)


def test_fetch_no_url_raises(tmp_path):
    handle = job_mod.JobHandle(
        backend="xai_video", job_id="req-1", status="done",
        extra={"poll_response": {"status": "done", "video": {}}},
    )
    with pytest.raises(XAIAPIError, match="no video.url"):
        XAIVideoBackend().fetch(handle, out_dir=tmp_path)


def test_fetch_downloads_to_target(monkeypatch, tmp_path):
    """Stub the download URL fetch and verify the bytes land at the
    expected path."""
    fake_bytes = b"FAKE_MP4_HEADER" + b"\x00" * 100

    def _fake_urlopen(req, timeout=None):
        return _fake_urlopen_response_raw(fake_bytes)

    monkeypatch.setattr(
        "athena.videogen.backends.xai.urllib.request.urlopen", _fake_urlopen,
    )

    handle = job_mod.JobHandle(
        backend="xai_video", job_id="req-abc", status="done",
        extra={
            "poll_response": {
                "status": "done",
                "video": {"url": "https://example.com/v.mp4"},
            }
        },
    )
    out_path = XAIVideoBackend().fetch(handle, out_dir=tmp_path)
    assert out_path == tmp_path / "req-abc.mp4"
    assert out_path.read_bytes() == fake_bytes


def _fake_urlopen_response_raw(body: bytes):
    class _Resp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return body
        def getcode(self):
            return 200
    return _Resp()
