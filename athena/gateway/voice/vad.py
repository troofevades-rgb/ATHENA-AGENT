"""Voice-activity detection — decides whether a frame contains speech.

Two implementations behind one Protocol:

  - :class:`WebrtcvadDetector` — the production choice (Google's WebRTC
    VAD via the optional ``webrtcvad`` package). Accurate, but constrained
    to 8/16/32/48 kHz audio and 10/20/30 ms frames.
  - :class:`EnergyDetector` — a dependency-free RMS-threshold fallback.
    Deterministic, so it's also what the tests use; good enough that the
    pipeline works on a host without ``webrtcvad`` installed.

:func:`resolve_detector` prefers webrtcvad and falls back to energy, so a
missing optional dep degrades quietly rather than breaking voice.
"""

from __future__ import annotations

import array
import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class SpeechDetector(Protocol):
    """Per-frame speech/no-speech decision."""

    def is_speech(self, frame_pcm: bytes, sample_rate: int) -> bool: ...


class EnergyDetector:
    """RMS-threshold VAD — no dependencies, fully deterministic.

    Computes the root-mean-square amplitude of the frame's s16le samples
    and calls it speech when it clears ``rms_threshold``. Crude versus a
    real VAD (it can't tell speech from any loud sound) but it never
    mis-frames and needs nothing installed — ideal as the test detector
    and the no-dep fallback.
    """

    def __init__(self, rms_threshold: float = 500.0) -> None:
        self.rms_threshold = float(rms_threshold)

    def is_speech(self, frame_pcm: bytes, sample_rate: int) -> bool:
        if not frame_pcm:
            return False
        samples = array.array("h")  # signed 16-bit
        # Trim a stray odd byte rather than raise on a malformed frame.
        usable = frame_pcm[: len(frame_pcm) - (len(frame_pcm) % 2)]
        samples.frombytes(usable)
        if not samples:
            return False
        mean_sq = sum(s * s for s in samples) / len(samples)
        return bool((mean_sq**0.5) >= self.rms_threshold)


class WebrtcvadDetector:
    """webrtcvad wrapper. ``aggressiveness`` 0 (most permissive) – 3."""

    def __init__(self, aggressiveness: int = 2) -> None:
        import webrtcvad  # local import — optional dep

        self._vad = webrtcvad.Vad(int(aggressiveness))

    def is_speech(self, frame_pcm: bytes, sample_rate: int) -> bool:
        try:
            return bool(self._vad.is_speech(frame_pcm, sample_rate))
        except Exception:  # noqa: BLE001 — a bad frame size must not crash a turn
            return False


def resolve_detector(cfg: Any = None, *, aggressiveness: int | None = None) -> SpeechDetector:
    """Return a usable detector: webrtcvad when importable, else energy."""
    agg = aggressiveness
    if agg is None:
        agg = int(getattr(cfg, "voice_vad_aggressiveness", 2) or 2)
    try:
        return WebrtcvadDetector(agg)
    except Exception as e:  # noqa: BLE001
        logger.info("voice: webrtcvad unavailable (%s) — using energy VAD", e)
        return EnergyDetector()
