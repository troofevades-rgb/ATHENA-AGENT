"""Platform-neutral voice core for the gateway (Discord-voice Phase 2).

The capture → segment → transcribe → agent-turn → speak pipeline, built so
it runs and is tested with no Discord and no audio hardware. The
Discord-specific receiver + playback (Phase 3) plug into these seams.

  - :class:`VoiceReceiver` / :class:`VoiceFrame` — the capture seam
  - :class:`SpeechDetector` (webrtcvad / energy) + :class:`UtteranceSegmenter`
  - :class:`VoiceSession` — the orchestrating state machine

See ``docs/design/discord-voice.md``.
"""

from __future__ import annotations

from .receiver import VoiceFrame, VoiceReceiver
from .segmenter import Utterance, UtteranceSegmenter
from .session import VoiceSession, VoiceSessionConfig, VoiceState, VoiceStats
from .vad import EnergyDetector, SpeechDetector, WebrtcvadDetector, resolve_detector

__all__ = [
    "EnergyDetector",
    "SpeechDetector",
    "Utterance",
    "UtteranceSegmenter",
    "VoiceFrame",
    "VoiceReceiver",
    "VoiceSession",
    "VoiceSessionConfig",
    "VoiceState",
    "VoiceStats",
    "WebrtcvadDetector",
    "resolve_detector",
]
