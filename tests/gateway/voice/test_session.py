"""VoiceSession orchestration — full pipeline against fakes, no Discord."""

from __future__ import annotations

import array
import asyncio
from collections.abc import AsyncIterator

from athena.gateway.events import MessageType
from athena.gateway.voice import (
    EnergyDetector,
    VoiceFrame,
    VoiceReceiver,
    VoiceSession,
    VoiceSessionConfig,
    VoiceState,
)

SR = 16_000
NS = SR * 20 // 1000


def _frame(value: int, speaker: str = "u1") -> VoiceFrame:
    return VoiceFrame(speaker_id=speaker, pcm=array.array("h", [value] * NS).tobytes())


SPEECH = _frame(6000)
SILENCE = _frame(0)
# One utterance = a speech run terminated by enough hangover silence.
ONE_UTTERANCE = [SPEECH] * 3 + [SILENCE] * 3


class FakeReceiver(VoiceReceiver):
    sample_rate = SR
    frame_ms = 20

    def __init__(self, frames: list[VoiceFrame]) -> None:
        self._frames = frames
        self.started = False
        self.stopped = False
        self.capture_calls: list[bool] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def set_capturing(self, on: bool) -> None:
        self.capture_calls.append(on)

    async def frames(self) -> AsyncIterator[VoiceFrame]:
        for f in self._frames:
            yield f


def _cfg(**kw) -> VoiceSessionConfig:
    base = dict(
        require_consent=False,
        sample_rate=SR,
        frame_ms=20,
        min_utterance_ms=40,
        max_utterance_ms=400,
        silence_hangover_ms=60,
        chat_id="vc1",
    )
    base.update(kw)
    return VoiceSessionConfig(**base)


def _session(rec, transcribe, run_turn, speak, **cfgkw) -> VoiceSession:
    return VoiceSession(
        receiver=rec,
        transcribe=transcribe,
        run_turn=run_turn,
        speak=speak,
        config=_cfg(**cfgkw),
        detector=EnergyDetector(rms_threshold=500),
    )


def test_full_pipeline_one_turn() -> None:
    events, spoken = [], []

    async def transcribe(u):
        return "hello athena"

    async def run_turn(e):
        events.append(e)
        return "hi there"

    async def speak(t):
        spoken.append(t)

    rec = FakeReceiver(ONE_UTTERANCE)
    s = _session(rec, transcribe, run_turn, speak)
    stats = asyncio.run(s.run())

    assert stats.utterances == 1 and stats.turns == 1
    assert len(events) == 1
    ev = events[0]
    assert ev.message_type == MessageType.AUDIO
    assert ev.text == "hello athena"
    assert ev.user_id == "u1" and ev.chat_id == "vc1" and ev.is_dm is False
    assert ev.raw.get("voice") is True
    assert spoken == ["hi there"]
    assert rec.started and rec.stopped
    assert s.state is VoiceState.STOPPED
    # Half-duplex: capture gated off then back on around the turn.
    assert rec.capture_calls[:2] == [False, True]


def test_flush_frame_ends_utterance_before_cap() -> None:
    # Speech with NO trailing hangover silence: the segmenter would ride to
    # the max cap, but a receiver-issued flush marker ends it immediately.
    events, spoken = [], []

    async def transcribe(u):
        return "flushed"

    async def run_turn(e):
        events.append(e)
        return "ok"

    async def speak(t):
        spoken.append(t)

    flush = VoiceFrame(speaker_id="u1", pcm=b"", flush=True)
    # 3 speech frames (60ms voiced, over the 40ms min) then a flush — and
    # NOT enough frames to reach the 400ms cap on their own.
    rec = FakeReceiver([SPEECH, SPEECH, SPEECH, flush])
    s = _session(rec, transcribe, run_turn, speak)
    stats = asyncio.run(s.run())
    assert stats.utterances == 1 and stats.turns == 1
    assert events[0].text == "flushed" and spoken == ["ok"]


def test_flush_frame_without_speech_is_noop() -> None:
    turns = []

    async def transcribe(u):
        return "x"

    async def run_turn(e):
        turns.append(e)
        return "y"

    async def speak(t):
        return None

    flush = VoiceFrame(speaker_id="u1", pcm=b"", flush=True)
    s = _session(FakeReceiver([flush, flush]), transcribe, run_turn, speak)
    stats = asyncio.run(s.run())
    assert stats.utterances == 0 and turns == []


def test_empty_transcript_runs_no_turn() -> None:
    turns, spoken = [], []

    async def transcribe(u):
        return "   "  # nothing intelligible

    async def run_turn(e):
        turns.append(e)
        return "x"

    async def speak(t):
        spoken.append(t)

    s = _session(FakeReceiver(ONE_UTTERANCE), transcribe, run_turn, speak)
    asyncio.run(s.run())
    assert turns == [] and spoken == []


def test_reply_silence_speaks_nothing() -> None:
    spoken = []

    async def transcribe(u):
        return "ping"

    async def run_turn(e):
        return "   "  # agent produced no speakable text

    async def speak(t):
        spoken.append(t)

    s = _session(FakeReceiver(ONE_UTTERANCE), transcribe, run_turn, speak)
    stats = asyncio.run(s.run())
    assert stats.turns == 1 and spoken == []


def test_consent_gate_blocks_capture() -> None:
    turns = []

    async def transcribe(u):
        return "hi"

    async def run_turn(e):
        turns.append(e)
        return "y"

    async def speak(t):
        return None

    s = _session(FakeReceiver(ONE_UTTERANCE), transcribe, run_turn, speak, require_consent=True)
    asyncio.run(s.run())
    assert turns == []  # consent never granted → nothing processed


def test_failure_isolation_continues_after_error() -> None:
    n = {"i": 0}
    seen = []

    async def transcribe(u):
        n["i"] += 1
        if n["i"] == 1:
            raise RuntimeError("stt boom")
        return "second"

    async def run_turn(e):
        seen.append(e.text)
        return "ok"

    async def speak(t):
        return None

    rec = FakeReceiver(ONE_UTTERANCE + ONE_UTTERANCE)
    s = _session(rec, transcribe, run_turn, speak)
    stats = asyncio.run(s.run())

    assert stats.errors == 1
    assert seen == ["second"]  # 2nd utterance handled despite the 1st failing
    assert s.state is VoiceState.STOPPED


def test_request_stop_ends_before_processing() -> None:
    async def transcribe(u):
        return "hi"

    async def run_turn(e):
        return "y"

    async def speak(t):
        return None

    s = _session(FakeReceiver([SPEECH] * 100), transcribe, run_turn, speak)
    s.request_stop()
    stats = asyncio.run(s.run())
    assert stats.turns == 0 and s.state is VoiceState.STOPPED
