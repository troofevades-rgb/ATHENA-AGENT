"""Deterministic silent-WAV TTS backend.

Always available, depends on nothing, and produces a valid mono PCM-s16le
WAV whose length scales with the input text. Two uses:

  - **tests** — the whole voice pipeline can be exercised end-to-end with
    no TTS engine and no audio hardware.
  - **explicit headless fallback** — pin ``tts_backend = "tts_stub"`` to
    keep the synthesis path working on a host without a real engine.

It is marked ``test_only`` so the resolver's *auto* path never selects it
silently (silence masquerading as speech is worse than "TTS unavailable").
It is only used when explicitly pinned.
"""

from __future__ import annotations

import logging
import os
import tempfile
import wave
from pathlib import Path
from typing import Any

from ....providers import register_provider
from ....providers.base import Capabilities, Provider
from ..base import DISCORD_SAMPLE_RATE, SynthResult

logger = logging.getLogger(__name__)

# ~60 ms of audio per character, clamped — enough that the duration is a
# stable, monotonic function of the text for tests without ever producing
# an absurdly long clip.
_SECONDS_PER_CHAR = 0.06
_MIN_SECONDS = 0.2
_MAX_SECONDS = 30.0


@register_provider
class StubTTSBackend(Provider):
    """Capability-only provider (not a chat backend) producing silent WAVs.

    Same shape as ``FasterWhisperLocalBackend`` / ``stub_video_local``:
    declares its media capability, stubs the chat ABC.
    """

    name: str = "tts_stub"
    requires_api_key: bool = False
    # The resolver's auto path skips this; pin explicitly to use it.
    test_only: bool = True

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        return Capabilities(
            text_to_speech=True,
            is_local=True,
            tool_calls=False,
            streaming=False,
        )

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key=api_key, **kwargs)

    # ---- chat ABC plumbing — not a chat backend ----

    def stream_chat(self, **kwargs: Any):  # noqa: D401
        raise NotImplementedError(
            "tts_stub is a speech-synthesis backend, not a chat provider; "
            "route via athena.audio.tts.resolve.resolve_tts_backend"
        )

    def parse_tool_calls(self, content: str, raw_response: dict[str, Any]):
        return content, []

    # ---- SpeechSynthBackend protocol ----

    def is_available(self) -> bool:
        return True

    def synthesize(
        self,
        text: str,
        *,
        out_path: Path | str | None = None,
        voice: str | None = None,
        sample_rate: int = DISCORD_SAMPLE_RATE,
    ) -> SynthResult:
        rate = int(sample_rate) if sample_rate and sample_rate > 0 else DISCORD_SAMPLE_RATE
        duration_s = max(_MIN_SECONDS, min(_MAX_SECONDS, len(text or "") * _SECONDS_PER_CHAR))
        n_frames = int(duration_s * rate)

        if out_path is not None:
            path = Path(out_path)
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="athena_tts_")
            os.close(fd)
            path = Path(tmp)

        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # s16
            wf.setframerate(rate)
            wf.writeframes(b"\x00\x00" * n_frames)  # silence

        return SynthResult(path=path, sample_rate=rate, duration_s=duration_s, backend=self.name)
