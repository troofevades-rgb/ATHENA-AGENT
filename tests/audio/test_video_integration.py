"""T4-04.3 — video_analyze ↔ audio_analyze integration.

Pins:
  - video_analyze mode=analyze invokes the audio_fn when one
    is available; the transcript lands in the result
  - audio_fn=None → no transcript field; analyze result still
    carries frames + per-frame analyses
  - audio_fn raising → analyze result still returns cleanly,
    just without the transcript (defensive — audio failure
    must not break video analysis)
  - the spec's "T4-02 video tool uses transcribe_track" call
    chain works end-to-end with a stub audio backend
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.video.analyze import _run as video_run
from tests.video.fixtures import FIXTURES_DIR, have_ffmpeg


_NEED_FFMPEG = pytest.mark.skipif(
    not have_ffmpeg(),
    reason="ffmpeg not on PATH",
)


def _cfg(tmp_path: Path, **overrides: Any) -> SimpleNamespace:
    base = dict(
        profile="default",
        video_enabled=True,
        vision_enabled=True,
        video_ffmpeg_path="ffmpeg",
        video_ffprobe_path="ffprobe",
        video_frames_dir=str(tmp_path / "frames"),
        video_max_frames=200,
        video_default_extract="keyframes",
        video_sampled_interval_s=5.0,
        # Audio side — values mostly irrelevant since we inject
        # _audio_fn directly, but resolve_paths/load_config
        # might reach for them in error paths.
        audio_analyze_enabled=True,
        audio_chunk_seconds=30.0,
        audio_chunk_overlap_s=2.0,
        audio_output_dir=str(tmp_path / "audio"),
        media_backend_prefer="local",
        provider="ollama",
        model="stub",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _route_profile_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "athena.video.analyze.profile_dir",
        lambda profile="default": tmp_path,
    )
    yield


@_NEED_FFMPEG
def test_analyze_mode_includes_transcript_when_audio_fn_available(
    tmp_path: Path,
):
    """The load-bearing T4-04.3 invariant: video.analyze calls
    audio_fn(path) and folds the transcript into the result."""
    seen_paths: list[Path] = []

    def _audio_stub(video_path: Path) -> dict:
        seen_paths.append(video_path)
        return {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "first beat"},
                {"start": 1.0, "end": 2.0, "text": "second beat"},
            ],
            "language": "en",
            "duration": 2.0,
        }

    def _vision_stub(frame_path: Path, prompt: str) -> str:
        return f"frame {Path(frame_path).name}"

    out = json.loads(video_run(
        mode="analyze",
        path=str(FIXTURES_DIR / "sample.mp4"),
        _cfg=_cfg(tmp_path),
        _provider_fn=_vision_stub,
        _audio_fn=_audio_stub,
    ))

    assert out["mode"] == "analyze"
    assert "transcript" in out
    assert len(out["transcript"]["segments"]) == 2
    assert out["transcript"]["segments"][0]["text"] == "first beat"
    assert out["transcript"]["language"] == "en"
    # And the audio_fn was called with the actual video path.
    assert len(seen_paths) == 1


@_NEED_FFMPEG
def test_analyze_mode_omits_transcript_when_audio_fn_returns_none(
    tmp_path: Path,
):
    """audio_fn(...) returns None → no transcript field. Result
    still includes frames + per-frame analyses (analyze without
    audio is a valid degraded mode)."""

    def _vision_stub(frame_path: Path, prompt: str) -> str:
        return "described"

    out = json.loads(video_run(
        mode="analyze",
        path=str(FIXTURES_DIR / "sample.mp4"),
        _cfg=_cfg(tmp_path),
        _provider_fn=_vision_stub,
        _audio_fn=lambda _path: None,
    ))

    assert "transcript" not in out
    assert "analyses" in out  # frames-side still ran


@_NEED_FFMPEG
def test_analyze_mode_handles_audio_fn_exception(tmp_path: Path):
    """audio_fn raising → analyze result still returns
    cleanly; the transcript is just absent. Audio failure
    must not break video analysis."""

    def _audio_raises(_path: Path) -> dict:
        raise RuntimeError("model offline")

    def _vision_stub(frame_path: Path, prompt: str) -> str:
        return "described"

    out = json.loads(video_run(
        mode="analyze",
        path=str(FIXTURES_DIR / "sample.mp4"),
        _cfg=_cfg(tmp_path),
        _provider_fn=_vision_stub,
        _audio_fn=_audio_raises,
    ))

    # No transcript field, but no crash + frame analysis intact.
    assert "transcript" not in out
    assert out["mode"] == "analyze"
    assert "analyses" in out


@_NEED_FFMPEG
def test_analyze_mode_no_audio_fn_no_transcript(tmp_path: Path, monkeypatch):
    """When _default_audio_transcribe_fn returns None (e.g.
    cfg.audio_analyze_enabled=False), the analyze path doesn't
    even try to transcribe. Pinned by setting the cfg flag
    False and asserting transcript field absent."""

    def _vision_stub(frame_path: Path, prompt: str) -> str:
        return "described"

    out = json.loads(video_run(
        mode="analyze",
        path=str(FIXTURES_DIR / "sample.mp4"),
        _cfg=_cfg(tmp_path, audio_analyze_enabled=False),
        _provider_fn=_vision_stub,
        # _audio_fn left None — the default factory will
        # short-circuit because audio_analyze_enabled=False.
    ))

    assert "transcript" not in out
