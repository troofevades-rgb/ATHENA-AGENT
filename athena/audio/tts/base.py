"""Text-to-speech backend contract — the synthesis mirror of the STT
``AudioBackend`` Protocol (``athena/audio/job.py``).

A ``SpeechSynthBackend`` turns text into a playable WAV. Backends are
*also* ``Provider`` subclasses that declare ``text_to_speech=True`` in
their static capabilities, so the same capability machinery that resolves
STT / vision / video / OCR resolves TTS too (see ``resolve.py``). Vendor
specifics — model loading, voice files, binaries, network transport —
stay isolated to one file under ``backends/``.

This is Phase 1 of the Discord-voice design (``docs/design/discord-voice.md``):
the synthesis half, useful on its own (a future ``speak`` tool can reuse
it) and independently testable with the ``tts_stub`` backend.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# Discord voice is natively 48 kHz; defaulting here keeps the eventual
# playback path resample-free. Backends may produce a different rate and
# report it on the result — the caller resamples if it must.
DISCORD_SAMPLE_RATE = 48_000


@dataclasses.dataclass
class SynthResult:
    """Output of one :meth:`SpeechSynthBackend.synthesize` call.

    ``path`` is a self-contained WAV (PCM s16le, mono) on disk that the
    caller owns and is responsible for deleting. ``sample_rate`` is the
    WAV's rate in Hz, ``duration_s`` the audio length in seconds, and
    ``backend`` records which backend produced it (for logs / the voice
    runbook).
    """

    path: Path
    sample_rate: int
    duration_s: float
    backend: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "sample_rate": int(self.sample_rate),
            "duration_s": round(float(self.duration_s), 3),
            "backend": self.backend,
        }


@runtime_checkable
class SpeechSynthBackend(Protocol):
    """The synthesis surface every TTS adapter satisfies.

    Backends should:

      - declare ``text_to_speech=True`` in ``static_capabilities()`` so
        the resolver picks them up; prefer ``is_local=True`` for
        on-device engines (text never leaves the host).
      - implement :meth:`is_available` as a cheap "can run here" probe
        (lib importable / binary present / voice file readable). The
        resolver consults it before returning a backend and falls
        through to the next candidate on False — never a crash.
      - write a self-contained WAV the caller owns. Raise only on a
        genuine synthesis failure (the voice session catches it and
        degrades the turn, per the design's failure-isolation contract).

    Implementations live under ``athena/audio/tts/backends/``.
    """

    name: str

    def is_available(self) -> bool:
        """Quick host-capability check. Must not load heavy models —
        that happens lazily on first :meth:`synthesize`."""
        ...

    def synthesize(
        self,
        text: str,
        *,
        out_path: Path | str | None = None,
        voice: str | None = None,
        sample_rate: int = DISCORD_SAMPLE_RATE,
    ) -> SynthResult:
        """Render ``text`` to a WAV.

        ``out_path`` — where to write; ``None`` means the backend makes a
        temp file the caller owns. ``voice`` — backend-specific voice id
        (``None`` = backend default). ``sample_rate`` — requested output
        rate in Hz (48 kHz is Discord voice's native rate).
        """
        ...
