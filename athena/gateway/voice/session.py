"""VoiceSession — the platform-neutral orchestrator for one voice channel.

It wires the capture → segment → transcribe → agent-turn → speak loop
together, and is deliberately built from **injected collaborators** so the
whole thing runs (and is tested) with no Discord, no audio hardware, and
no real STT/TTS:

  - ``receiver``   — a :class:`VoiceReceiver` yielding PCM frames
  - ``transcribe`` — ``Utterance -> str`` (prod: faster-whisper off-thread)
  - ``run_turn``   — ``MessageEvent -> str`` (prod: ``daemon.handle_inbound``)
  - ``speak``      — ``str -> None`` (prod: TTS resolve + playback)

The agent turn produces the same :class:`MessageEvent` the text path
produces (``message_type=AUDIO``), so it inherits routing, the agent pool,
approvals, and continuity unchanged — voice is an I/O skin, not a new
agent (see ``docs/design/discord-voice.md``).

Tier-1 scope: half-duplex, single in-flight utterance, command-initiated.
Resource caps (idle disconnect, max session lifetime) and mid-playback
barge-in are Phase 4 hardening; this module establishes the state machine
and the failure-isolation contract.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
from collections.abc import Awaitable, Callable

from ..events import MessageEvent, MessageType
from .receiver import VoiceReceiver
from .segmenter import Utterance, UtteranceSegmenter
from .vad import SpeechDetector, resolve_detector

logger = logging.getLogger(__name__)

TranscribeFn = Callable[[Utterance], Awaitable[str]]
RunTurnFn = Callable[[MessageEvent], Awaitable[str]]
SpeakFn = Callable[[str], Awaitable[None]]


class VoiceState(enum.Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    STOPPED = "stopped"


@dataclasses.dataclass
class VoiceSessionConfig:
    """Per-session knobs. Phase 3 maps ``cfg.gateway.platforms.discord.voice``
    onto this; nothing here reaches into global config so the session stays
    self-contained and testable."""

    platform: str = "discord"
    chat_id: str = ""
    require_consent: bool = True
    sample_rate: int = 48_000
    frame_ms: int = 20
    min_utterance_ms: int = 400
    # Hard cap on a single utterance. Bounds worst-case latency when
    # end-of-speech isn't detected (e.g. an open-mic room whose continuous
    # background the VAD flags as speech) — the turn fires at the cap
    # rather than making the speaker wait. In that environment the cap is
    # effectively the *listen window* every turn, so it's the dominant
    # capture latency: 6s still fits a spoken command/question while
    # shaving 4s off each turn vs the original 10s.
    max_utterance_ms: int = 6_000
    silence_hangover_ms: int = 800
    # webrtcvad 0 (permissive) – 3 (aggressive non-speech rejection).
    # 3 is the most robust at detecting the *end* of speech over a noisy
    # mic — the failure mode that otherwise runs an utterance to the cap.
    vad_aggressiveness: int = 3


@dataclasses.dataclass
class VoiceStats:
    utterances: int = 0
    turns: int = 0
    dropped_frames: int = 0
    errors: int = 0


class VoiceSession:
    def __init__(
        self,
        *,
        receiver: VoiceReceiver,
        transcribe: TranscribeFn,
        run_turn: RunTurnFn,
        speak: SpeakFn,
        config: VoiceSessionConfig | None = None,
        detector: SpeechDetector | None = None,
    ) -> None:
        self.config = config or VoiceSessionConfig()
        self.receiver = receiver
        self._transcribe = transcribe
        self._run_turn = run_turn
        self._speak = speak
        self.state = VoiceState.IDLE
        self.stats = VoiceStats()
        self._stop = False
        self._consent = not self.config.require_consent
        det = detector or resolve_detector(aggressiveness=self.config.vad_aggressiveness)
        self._segmenter = UtteranceSegmenter(
            det,
            sample_rate=self.config.sample_rate,
            frame_ms=self.config.frame_ms,
            min_utterance_ms=self.config.min_utterance_ms,
            max_utterance_ms=self.config.max_utterance_ms,
            silence_hangover_ms=self.config.silence_hangover_ms,
        )

    # ---- external controls ----

    def grant_consent(self) -> None:
        """Allow capture to begin (when ``require_consent`` is set)."""
        self._consent = True

    def request_stop(self) -> None:
        """Ask the session to end after the current frame. The run loop
        observes this and tears down. (Mid-playback barge-in is Phase 4.)"""
        self._stop = True

    # ---- main loop ----

    async def run(self) -> VoiceStats:
        """Capture → segment → turn → speak until stop / channel close.

        Never raises out of the per-utterance work: a transcribe / turn /
        speak fault is isolated, counted, and the session returns to
        LISTENING. Only a receiver failure ends the loop (via teardown).
        """
        self.state = VoiceState.CONNECTING
        await self.receiver.start()
        self.state = VoiceState.LISTENING
        try:
            async for frame in self.receiver.frames():
                if self._stop:
                    break
                if not self._consent:
                    continue  # gate capture until consent is granted
                if self.state is not VoiceState.LISTENING:
                    # Single in-flight utterance: drop audio captured while
                    # busy so we don't backlog or transcribe our own voice.
                    self.stats.dropped_frames += 1
                    continue
                # A flush marker (receiver detected end-of-speech by wall
                # clock) closes the in-progress utterance now; a normal frame
                # feeds the VAD state machine.
                if frame.flush:
                    utterance = self._segmenter.flush()
                else:
                    utterance = self._segmenter.feed(frame)
                if utterance is not None:
                    self.stats.utterances += 1
                    await self._handle(utterance)
        finally:
            await self._teardown()
        return self.stats

    async def _handle(self, utterance: Utterance) -> None:
        # Half-duplex: tell the receiver to stop delivering while we work,
        # and clear any partial buffer so backlog can't become a phantom.
        self.receiver.set_capturing(False)
        try:
            self.state = VoiceState.TRANSCRIBING
            text = (await self._transcribe(utterance)).strip()
            if not text:
                return  # nothing intelligible — back to listening
            self.state = VoiceState.THINKING
            event = self._build_event(utterance, text)
            reply = (await self._run_turn(event) or "").strip()
            self.stats.turns += 1
            if reply:
                self.state = VoiceState.SPEAKING
                await self._speak(reply)
        except Exception as e:  # noqa: BLE001 — a turn fault must not kill the session
            self.stats.errors += 1
            logger.warning("voice: turn failed, continuing: %s", e)
        finally:
            self._segmenter.reset()
            if self.state is not VoiceState.STOPPED:
                self.state = VoiceState.LISTENING
            self.receiver.set_capturing(True)

    def _build_event(self, utterance: Utterance, text: str) -> MessageEvent:
        return MessageEvent(
            platform=self.config.platform,
            chat_id=self.config.chat_id,
            user_id=utterance.speaker_id,
            text=text,
            message_type=MessageType.AUDIO,
            is_dm=False,
            raw={"voice": True, "duration_s": round(utterance.duration_s, 3)},
        )

    async def _teardown(self) -> None:
        self.state = VoiceState.STOPPED
        try:
            await self.receiver.stop()
        except Exception as e:  # noqa: BLE001
            logger.debug("voice: receiver.stop() raised on teardown: %s", e)
