"""VAD + utterance segmentation — pure, synthetic-PCM tests (no audio I/O)."""

from __future__ import annotations

import array

from athena.gateway.voice.receiver import VoiceFrame
from athena.gateway.voice.segmenter import UtteranceSegmenter
from athena.gateway.voice.vad import EnergyDetector

SR = 16_000
FRAME_MS = 20
NS = SR * FRAME_MS // 1000  # samples per frame (320)


def _frame(value: int, speaker: str = "u1") -> VoiceFrame:
    return VoiceFrame(speaker_id=speaker, pcm=array.array("h", [value] * NS).tobytes())


SPEECH = _frame(6000)
SILENCE = _frame(0)


# ---- EnergyDetector ------------------------------------------------------


def test_energy_detector_silence_vs_speech() -> None:
    d = EnergyDetector(rms_threshold=500)
    assert d.is_speech(SILENCE.pcm, SR) is False
    assert d.is_speech(SPEECH.pcm, SR) is True


def test_energy_detector_empty_and_odd_bytes() -> None:
    d = EnergyDetector()
    assert d.is_speech(b"", SR) is False
    assert d.is_speech(b"\x01", SR) is False  # stray odd byte, no crash


# ---- segmenter -----------------------------------------------------------


def _seg(min_ms: int = 40, max_ms: int = 200, hang_ms: int = 60) -> UtteranceSegmenter:
    return UtteranceSegmenter(
        EnergyDetector(rms_threshold=500),
        sample_rate=SR,
        frame_ms=FRAME_MS,
        min_utterance_ms=min_ms,
        max_utterance_ms=max_ms,
        silence_hangover_ms=hang_ms,
    )


def _feed_all(seg: UtteranceSegmenter, frames: list[VoiceFrame]) -> list:
    return [u for u in (seg.feed(f) for f in frames) if u is not None]


def test_emits_one_utterance_on_hangover() -> None:
    seg = _seg(hang_ms=60)
    out = _feed_all(seg, [SPEECH] * 3 + [SILENCE] * 3)
    assert len(out) == 1
    assert out[0].speaker_id == "u1"
    # 3 voiced + 3 silence frames buffered = 120 ms of audio.
    assert abs(out[0].duration_s - 0.12) < 0.005


def test_drops_blip_below_min_voiced() -> None:
    # One 20 ms voiced frame then silence — voiced (20) < min (40) → dropped,
    # even though trailing hangover silence pads the buffer.
    seg = _seg(min_ms=40, hang_ms=60)
    out = _feed_all(seg, [SPEECH] + [SILENCE] * 3)
    assert out == []


def test_max_length_force_emits() -> None:
    seg = _seg(min_ms=40, max_ms=100, hang_ms=10_000)  # hangover won't fire
    # 6 continuous speech frames = 120 ms > max 100 ms → force-emit mid-run.
    out = _feed_all(seg, [SPEECH] * 6)
    assert len(out) == 1


def test_flush_emits_in_progress() -> None:
    seg = _seg(min_ms=40)
    assert seg.feed(SPEECH) is None
    assert seg.feed(SPEECH) is None  # 40 ms voiced, no hangover yet
    u = seg.flush()
    assert u is not None and u.speaker_id == "u1"


def test_two_separate_utterances() -> None:
    seg = _seg(hang_ms=40)
    frames = [SPEECH] * 3 + [SILENCE] * 2 + [SPEECH] * 3 + [SILENCE] * 2
    out = _feed_all(seg, frames)
    assert len(out) == 2
