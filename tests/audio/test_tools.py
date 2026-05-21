"""T4-04.2 — audio_analyze tool tests.

Pins:
  - tool registered under the vision toolset
  - no backend → structured `available=False, reason=...`
  - happy path returns segments + writes transcript artifact
    + writes audit row
  - diarize mode passes diarize=True to the backend
  - diarize without cfg flag enabled → diarize=False (the
    operator opt-in gate)
  - classify / full modes set content_type
  - audio_analyze_enabled=False short-circuits
  - missing file rejected
  - unknown mode rejected
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.audio import tools as audio_tools
from athena.audio.tools import _run, transcribe_track, VALID_MODES
from tests.audio.conftest import StubAudioBackend, make_wav


def _cfg(tmp_path: Path, **overrides: Any) -> SimpleNamespace:
    base = dict(
        profile="default",
        audio_analyze_enabled=True,
        audio_backend_prefer="local",
        audio_diarization_enabled=False,
        audio_chunk_seconds=30.0,
        audio_chunk_overlap_s=2.0,
        audio_output_dir=str(tmp_path / "audio"),
        audio_whisper_model="base",
        audio_whisper_device="auto",
        audio_whisper_compute_type="auto",
        media_backend_prefer="local",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _route_profile_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "athena.audio.tools.profile_dir",
        lambda profile="default": tmp_path,
    )
    yield


# ---------------------------------------------------------------
# tool registration
# ---------------------------------------------------------------


def test_tool_registered_in_vision_toolset():
    import athena.tools  # noqa: F401 — trigger registration
    from athena.tools.registry import get_tool
    t = get_tool("audio_analyze")
    assert t is not None
    assert t.toolset == "vision"


def test_schema_lists_all_modes():
    import athena.tools  # noqa: F401
    from athena.tools.registry import get_tool
    t = get_tool("audio_analyze")
    enum = t.parameters["properties"]["mode"]["enum"]
    assert set(enum) == set(VALID_MODES)


# ---------------------------------------------------------------
# gate + validation
# ---------------------------------------------------------------


def test_audio_disabled_short_circuits(tmp_path: Path):
    wav = make_wav(tmp_path / "a.wav", duration_s=0.5)
    out = json.loads(_run(
        path=str(wav),
        _cfg=_cfg(tmp_path, audio_analyze_enabled=False),
        _backend=StubAudioBackend(),
    ))
    assert out["available"] is False
    assert "audio_analyze_enabled=False" in out["error"]


def test_unknown_mode_rejected(tmp_path: Path):
    wav = make_wav(tmp_path / "a.wav")
    out = json.loads(_run(
        path=str(wav), mode="hum",
        _cfg=_cfg(tmp_path),
        _backend=StubAudioBackend(),
    ))
    assert out["available"] is False
    assert "unknown mode" in out["error"]


def test_missing_path_rejected(tmp_path: Path):
    out = json.loads(_run(
        path=None,
        _cfg=_cfg(tmp_path),
        _backend=StubAudioBackend(),
    ))
    assert out["available"] is False
    assert "path is required" in out["error"]


def test_missing_file_rejected(tmp_path: Path):
    out = json.loads(_run(
        path=str(tmp_path / "nope.wav"),
        _cfg=_cfg(tmp_path),
        _backend=StubAudioBackend(),
    ))
    assert out["available"] is False
    assert "file not found" in out["error"]


def test_no_backend_branch_via_monkeypatch(tmp_path: Path, monkeypatch):
    wav = make_wav(tmp_path / "a.wav")
    monkeypatch.setattr(audio_tools, "_resolve_backend", lambda cfg: None)
    out = json.loads(_run(
        path=str(wav),
        _cfg=_cfg(tmp_path),
    ))
    assert out["available"] is False
    assert "no audio backend configured" in out["reason"]


# ---------------------------------------------------------------
# happy paths through the tool
# ---------------------------------------------------------------


def test_transcribe_mode_returns_segments(tmp_path: Path):
    wav = make_wav(tmp_path / "a.wav", duration_s=0.5)
    backend = StubAudioBackend(per_chunk_segments=2)
    out = json.loads(_run(
        path=str(wav), mode="transcribe",
        _cfg=_cfg(tmp_path),
        _backend=backend,
    ))
    assert out["available"] is True
    assert out["mode"] == "transcribe"
    assert len(out["segments"]) == 2
    assert all("text" in s for s in out["segments"])
    # Transcript artifact written.
    assert Path(out["transcript_path"]).exists()
    # sha256 + length present.
    assert len(out["sha256"]) == 64


def test_transcribe_writes_audit_row(tmp_path: Path):
    wav = make_wav(tmp_path / "a.wav", duration_s=0.5)
    backend = StubAudioBackend(per_chunk_segments=1)
    _run(
        path=str(wav), mode="transcribe",
        _cfg=_cfg(tmp_path),
        _backend=backend,
    )
    audit = tmp_path / "audio_audit.jsonl"
    rows = [json.loads(l) for l in audit.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    r = rows[0]
    assert r["mode"] == "transcribe"
    assert "transcript_path" in r["extra"]
    assert r["extra"]["segment_count"] == 1


def test_transcript_text_file_alongside_json(tmp_path: Path):
    """The sidecar .txt has one segment per line — grep-friendly
    output operators can read at a glance."""
    wav = make_wav(tmp_path / "a.wav")
    backend = StubAudioBackend(per_chunk_segments=2)
    out = json.loads(_run(
        path=str(wav),
        _cfg=_cfg(tmp_path),
        _backend=backend,
    ))
    json_path = Path(out["transcript_path"])
    txt_path = json_path.with_suffix(".txt")
    assert json_path.exists() and txt_path.exists()
    txt = txt_path.read_text(encoding="utf-8")
    # 2 segments → 2 lines.
    assert txt.count("\n") == 2


# ---------------------------------------------------------------
# diarize mode + opt-in gating
# ---------------------------------------------------------------


def test_diarize_mode_passes_diarize_true_when_enabled(tmp_path: Path):
    wav = make_wav(tmp_path / "a.wav")
    backend = StubAudioBackend(diarize_supported=True, per_chunk_segments=2)
    _run(
        path=str(wav), mode="diarize",
        _cfg=_cfg(tmp_path, audio_diarization_enabled=True),
        _backend=backend,
    )
    # Backend received diarize=True
    assert backend.transcribe_calls[0]["diarize"] is True


def test_diarize_mode_passes_diarize_false_when_disabled(tmp_path: Path):
    """audio_diarization_enabled=False (default) is the
    operator-level opt-in gate. Even mode=diarize doesn't
    fire diarization without it — the backend gets diarize=False."""
    wav = make_wav(tmp_path / "a.wav")
    backend = StubAudioBackend(diarize_supported=True, per_chunk_segments=1)
    _run(
        path=str(wav), mode="diarize",
        _cfg=_cfg(tmp_path, audio_diarization_enabled=False),
        _backend=backend,
    )
    assert backend.transcribe_calls[0]["diarize"] is False


def test_diarize_segments_carry_speaker_when_supported(tmp_path: Path):
    wav = make_wav(tmp_path / "a.wav")
    backend = StubAudioBackend(
        diarize_supported=True, per_chunk_segments=2,
    )
    out = json.loads(_run(
        path=str(wav), mode="diarize",
        _cfg=_cfg(tmp_path, audio_diarization_enabled=True),
        _backend=backend,
    ))
    speakers = [s.get("speaker") for s in out["segments"]]
    assert any(s is not None for s in speakers)


def test_diarize_segments_no_speaker_when_unsupported(tmp_path: Path):
    """A backend that doesn't support diarization returns
    segments with speaker=None — the contract. The tool
    accepts this without error; the caller sees no speaker
    fields in the output."""
    wav = make_wav(tmp_path / "a.wav")
    backend = StubAudioBackend(
        diarize_supported=False, per_chunk_segments=2,
    )
    out = json.loads(_run(
        path=str(wav), mode="diarize",
        _cfg=_cfg(tmp_path, audio_diarization_enabled=True),
        _backend=backend,
    ))
    for s in out["segments"]:
        assert "speaker" not in s  # to_dict omits None


# ---------------------------------------------------------------
# classify + full modes
# ---------------------------------------------------------------


def test_classify_mode_sets_content_type(tmp_path: Path):
    wav = make_wav(tmp_path / "a.wav")
    backend = StubAudioBackend(content_type="music", per_chunk_segments=1)
    out = json.loads(_run(
        path=str(wav), mode="classify",
        _cfg=_cfg(tmp_path),
        _backend=backend,
    ))
    assert out["content_type"] == "music"


def test_full_mode_carries_everything(tmp_path: Path):
    wav = make_wav(tmp_path / "a.wav")
    backend = StubAudioBackend(
        per_chunk_segments=2,
        diarize_supported=True,
        content_type="speech",
    )
    out = json.loads(_run(
        path=str(wav), mode="full",
        _cfg=_cfg(tmp_path, audio_diarization_enabled=True),
        _backend=backend,
    ))
    assert out["content_type"] == "speech"
    assert len(out["segments"]) == 2
    speakers = [s.get("speaker") for s in out["segments"]]
    assert any(s is not None for s in speakers)


# ---------------------------------------------------------------
# transcribe_track — composable helper for T4-02 video
# ---------------------------------------------------------------


def test_transcribe_track_returns_result_directly(tmp_path: Path):
    wav = make_wav(tmp_path / "a.wav")
    backend = StubAudioBackend(per_chunk_segments=3)
    result = transcribe_track(
        wav, cfg=_cfg(tmp_path), backend=backend,
    )
    assert len(result.segments) == 3
    assert result.language == "en"


def test_transcribe_track_no_backend_returns_empty(tmp_path: Path, monkeypatch):
    wav = make_wav(tmp_path / "a.wav")
    monkeypatch.setattr(audio_tools, "_resolve_backend", lambda cfg: None)
    result = transcribe_track(wav, cfg=_cfg(tmp_path))
    assert result.segments == []


def test_transcribe_track_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        transcribe_track(
            tmp_path / "nope.wav",
            cfg=_cfg(tmp_path),
            backend=StubAudioBackend(),
        )


# ---------------------------------------------------------------
# Backend exception → structured error (no crash into the model loop)
# ---------------------------------------------------------------


def test_backend_exception_surfaces_as_structured_error(tmp_path: Path):
    wav = make_wav(tmp_path / "a.wav")
    backend = StubAudioBackend(
        raise_on_transcribe=RuntimeError("model offline"),
    )
    out = json.loads(_run(
        path=str(wav),
        _cfg=_cfg(tmp_path),
        _backend=backend,
    ))
    assert out["available"] is True
    assert "transcribe failed" in out["error"]
    assert "model offline" in out["error"]
