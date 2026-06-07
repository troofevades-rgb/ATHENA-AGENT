"""Phase 1 of the Discord-voice design: the TTS backend abstraction.

Hermetic — the stub backend needs no engine or audio hardware, and the
real backends' availability is probed, not exercised, so these run
anywhere (piper is not installed in CI → reported unavailable).
"""

from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace

from athena.audio.tts import (
    DISCORD_SAMPLE_RATE,
    SpeechSynthBackend,
    SynthResult,
    resolve_tts_backend,
)
from athena.audio.tts.backends.piper_local import PiperLocalBackend
from athena.audio.tts.backends.stub import StubTTSBackend


def _cfg(**kw):
    # Neutralize every real local backend so resolver-LOGIC tests stay
    # hermetic: empty tts_voice → piper unavailable; bogus kokoro paths →
    # kokoro unavailable even on a dev box that has the model files at the
    # default ~/.athena/voices/ location. Tests that want a backend pin it.
    base = {
        "tts_backend": "",
        "tts_voice": "",
        "kokoro_voice": "af_heart",
        "kokoro_model_path": "/nonexistent/kokoro-v1.0.onnx",
        "kokoro_voices_path": "/nonexistent/voices-v1.0.bin",
    }
    base.update(kw)
    return SimpleNamespace(**base)


# ---- result / capability shapes ------------------------------------------


def test_synth_result_to_dict() -> None:
    p = Path("/tmp/x.wav")
    r = SynthResult(path=p, sample_rate=48000, duration_s=1.2345, backend="b")
    d = r.to_dict()
    assert d == {"path": str(p), "sample_rate": 48000, "duration_s": 1.234, "backend": "b"}


def test_stub_declares_text_to_speech_capability() -> None:
    caps = StubTTSBackend.static_capabilities()
    assert caps.supports("text_to_speech") is True
    assert caps.is_local is True


def test_stub_satisfies_protocol() -> None:
    assert isinstance(StubTTSBackend(), SpeechSynthBackend)


# ---- stub synthesis ------------------------------------------------------


def test_stub_synthesize_writes_valid_wav(tmp_path: Path) -> None:
    out = tmp_path / "hi.wav"
    res = StubTTSBackend().synthesize("hello there", out_path=out, sample_rate=48000)
    assert res.path == out and out.is_file()
    assert res.sample_rate == 48000 and res.backend == "tts_stub"
    with wave.open(str(out), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 48000
        assert wf.getnframes() > 0
    # Frame count matches the reported duration.
    assert abs(res.duration_s - (wf.getnframes() / 48000)) < 0.01


def test_stub_duration_grows_with_text() -> None:
    b = StubTTSBackend()
    short = b.synthesize("hi")
    long = b.synthesize("a much, much longer sentence to synthesize")
    try:
        assert long.duration_s > short.duration_s
    finally:
        short.path.unlink(missing_ok=True)
        long.path.unlink(missing_ok=True)


def test_stub_makes_temp_file_when_no_out_path() -> None:
    res = StubTTSBackend().synthesize("hi")
    try:
        assert res.path.is_file()
    finally:
        res.path.unlink(missing_ok=True)


# ---- piper availability (honest gating) ----------------------------------


def test_piper_unavailable_without_voice_model() -> None:
    # Even if piper happened to be installed, no voice is configured → not
    # available. (In CI piper isn't installed either; both paths → False.)
    assert PiperLocalBackend(cfg=_cfg()).is_available() is False


# ---- resolver ------------------------------------------------------------


def test_resolve_returns_none_when_nothing_available() -> None:
    # piper unavailable (no voice / not installed); stub is test_only and
    # excluded from auto-selection → honest None, not silent stub.
    assert resolve_tts_backend(_cfg()) is None


def test_resolve_honors_explicit_stub_pin() -> None:
    backend = resolve_tts_backend(_cfg(tts_backend="tts_stub"))
    assert backend is not None
    assert backend.name == "tts_stub"
    res = backend.synthesize("pinned")
    try:
        assert res.path.is_file()
    finally:
        res.path.unlink(missing_ok=True)


def test_resolve_unknown_pin_falls_through_to_none() -> None:
    # Unknown backend name → warn + broker → nothing available → None.
    assert resolve_tts_backend(_cfg(tts_backend="does_not_exist")) is None
