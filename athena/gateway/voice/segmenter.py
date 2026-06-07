"""Utterance segmentation: turn a frame stream into complete utterances.

Feed fixed-size :class:`~athena.gateway.voice.receiver.VoiceFrame`s; the
segmenter tracks a small VAD state machine and returns a completed
:class:`Utterance` when a run of speech ends (trailing silence exceeds the
hangover) or hits the max-length cap. It is **pure and synchronous** — no
audio I/O, no async — so it's exhaustively testable with synthetic PCM.

  silence ──speech──► in-speech ──hangover of silence / max length──► emit
"""

from __future__ import annotations

import dataclasses

from .receiver import VoiceFrame
from .vad import SpeechDetector


@dataclasses.dataclass(frozen=True)
class Utterance:
    """One segmented utterance ready for transcription.

    ``pcm`` is the concatenated mono s16le audio of the utterance.
    ``duration_s`` is derived from the byte length at ``sample_rate``.
    """

    pcm: bytes
    sample_rate: int
    speaker_id: str

    @property
    def duration_s(self) -> float:
        return len(self.pcm) / (self.sample_rate * 2) if self.sample_rate else 0.0


class UtteranceSegmenter:
    """VAD-driven utterance boundary detector.

    Parameters mirror the voice config: ``min_utterance_ms`` drops blips,
    ``max_utterance_ms`` force-emits an over-long run, ``silence_hangover_ms``
    is the trailing silence that ends an utterance.
    """

    def __init__(
        self,
        detector: SpeechDetector,
        *,
        sample_rate: int = 48_000,
        frame_ms: int = 20,
        min_utterance_ms: int = 400,
        max_utterance_ms: int = 30_000,
        silence_hangover_ms: int = 800,
    ) -> None:
        self._detector = detector
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.min_utterance_ms = min_utterance_ms
        self.max_utterance_ms = max_utterance_ms
        self.silence_hangover_ms = silence_hangover_ms
        self.reset()

    def reset(self) -> None:
        """Drop any in-progress utterance. Called after a turn so audio
        buffered while the agent was busy / speaking can't form a phantom
        utterance."""
        self._in_speech = False
        self._buf = bytearray()
        self._voiced_ms = 0  # speech-only — gates min_utterance_ms
        self._total_ms = 0  # speech + trailing silence — gates max
        self._silence_ms = 0
        self._speaker = ""

    def feed(self, frame: VoiceFrame) -> Utterance | None:
        """Consume one frame; return a completed utterance, or None."""
        speech = self._detector.is_speech(frame.pcm, self.sample_rate)

        if not self._in_speech:
            if speech:
                self._in_speech = True
                self._buf = bytearray(frame.pcm)
                self._voiced_ms = self.frame_ms
                self._total_ms = self.frame_ms
                self._silence_ms = 0
                self._speaker = frame.speaker_id
            return None

        # Mid-utterance: keep accumulating (including the trailing silence,
        # which a backend's own VAD trims; we only use it to find the end).
        self._buf += frame.pcm
        self._total_ms += self.frame_ms
        if speech:
            self._voiced_ms += self.frame_ms
            self._silence_ms = 0
        else:
            self._silence_ms += self.frame_ms

        if self._silence_ms >= self.silence_hangover_ms:
            return self._emit()
        if self._total_ms >= self.max_utterance_ms:
            return self._emit()
        return None

    def flush(self) -> Utterance | None:
        """Emit any in-progress utterance — call at end-of-stream."""
        return self._emit() if self._in_speech else None

    def _emit(self) -> Utterance | None:
        pcm = bytes(self._buf)
        speaker = self._speaker
        # min gate is on VOICED audio, not total — trailing hangover
        # silence must not rescue a blip from being dropped.
        voiced_ms = self._voiced_ms
        self.reset()
        if voiced_ms < self.min_utterance_ms:
            return None  # too little actual speech — drop
        return Utterance(pcm=pcm, sample_rate=self.sample_rate, speaker_id=speaker)
