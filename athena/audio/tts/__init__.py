"""Text-to-speech — the synthesis half of athena's audio stack.

Phase 1 of the Discord-voice design (``docs/design/discord-voice.md``):
a ``SpeechSynthBackend`` Protocol that mirrors the STT ``AudioBackend``,
two in-tree backends (``tts_piper_local`` real / ``tts_stub`` for tests +
headless fallback), and a config-pinned, local-first resolver. Useful on
its own — a future ``speak`` tool can reuse it without any voice/gateway
code.

Public surface::

    from athena.audio.tts import resolve_tts_backend, SpeechSynthBackend, SynthResult

    backend = resolve_tts_backend(cfg)      # None when nothing is available
    if backend is not None:
        result = backend.synthesize("hello there")
        play(result.path)                   # caller owns + deletes the WAV
"""

from __future__ import annotations

from .base import DISCORD_SAMPLE_RATE, SpeechSynthBackend, SynthResult
from .resolve import resolve_tts_backend

__all__ = [
    "DISCORD_SAMPLE_RATE",
    "SpeechSynthBackend",
    "SynthResult",
    "resolve_tts_backend",
]
