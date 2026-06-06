"""Platform-neutral audio-capture seam for voice sessions.

A :class:`VoiceReceiver` yields fixed-duration frames of mono PCM s16le
audio from a voice channel. The Discord implementation (Phase 3) wraps
``discord-ext-voice-recv``; the test fake yields scripted frames. Keeping
this an ABC is what lets the whole voice pipeline — segmentation, STT,
the agent turn, TTS — be built and tested with zero Discord and zero
audio hardware (see ``docs/design/discord-voice.md``).
"""

from __future__ import annotations

import abc
import dataclasses
from collections.abc import AsyncIterator


@dataclasses.dataclass(frozen=True)
class VoiceFrame:
    """One fixed-duration frame of audio from a single speaker.

    ``pcm`` is mono 16-bit signed little-endian samples at the receiver's
    ``sample_rate``. ``speaker_id`` is the platform's stable id for whoever
    produced it (v1 segments whoever crosses VAD; per-speaker separation is
    a Tier-2 concern but the tag is carried so it's available later).

    ``flush`` flips this from an audio frame into a *control* marker: an
    end-of-utterance signal carrying no audio (``pcm`` empty). A receiver
    emits one when it detects — by wall clock — that the active speaker has
    gone quiet, so the session can close the utterance immediately rather
    than wait for the segmenter's max-length cap. This matters in an
    open-mic channel where background audio streams continuously and the
    per-frame VAD never sees the silence the segmenter needs: the segmenter
    is pure/synchronous and can't watch the clock, but the receiver can.
    """

    speaker_id: str
    pcm: bytes
    flush: bool = False


class VoiceReceiver(abc.ABC):
    """Captures audio from a voice channel as a stream of PCM frames.

    Subclasses set :attr:`sample_rate` and :attr:`frame_ms` to describe
    the frames :meth:`frames` yields. 48 kHz / 20 ms is Discord's native
    voice cadence and the default.
    """

    sample_rate: int = 48_000
    frame_ms: int = 20

    @property
    def bytes_per_frame(self) -> int:
        """Expected length of each frame's ``pcm`` (mono s16le)."""
        return int(self.sample_rate * self.frame_ms / 1000) * 2

    @abc.abstractmethod
    async def start(self) -> None:
        """Join / begin capture. Idempotent."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Stop capture and release the connection. Idempotent."""

    @abc.abstractmethod
    def frames(self) -> AsyncIterator[VoiceFrame]:
        """Async-iterate captured frames until :meth:`stop` or the channel
        closes. Implementations are async generators."""
        ...

    def set_capturing(self, on: bool) -> None:
        """Half-duplex hint: while ``False`` the receiver should discard
        incoming audio instead of delivering it (so the session doesn't
        capture / backlog Athena's own playback). Default no-op — receivers
        that can't gate capture simply keep delivering and the session's
        state guard drops frames instead. Overridden by real receivers."""
        return None
