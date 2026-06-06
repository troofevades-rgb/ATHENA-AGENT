"""Discord voice plumbing — pure helpers, the receiver PCM path, and the
collaborator factories, all with fakes (no discord, no audio hardware).

The live receiver sink + FFmpeg playback need a real bot (the dogfood
runbook); everything reachable without discord is covered here.
"""

from __future__ import annotations

import array
import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from athena.audio.job import Segment, TranscribeResult
from athena.audio.tts import SynthResult
from athena.gateway.events import MessageEvent
from athena.gateway.platforms.discord_voice import (
    DiscordVoiceReceiver,
    FrameChunker,
    make_speak,
    make_transcribe,
    make_voice_run_turn,
    stereo_to_mono,
)
from athena.gateway.voice.segmenter import Utterance

# ---- pure helpers --------------------------------------------------------


def test_stereo_to_mono_averages_pairs() -> None:
    stereo = array.array("h", [100, 200, 100, 200]).tobytes()  # two L/R pairs
    mono = array.array("h")
    mono.frombytes(stereo_to_mono(stereo))
    assert list(mono) == [150, 150]


def test_stereo_to_mono_drops_partial_pair() -> None:
    assert stereo_to_mono(b"\x01\x02") == b""  # < one 4-byte L/R sample


def test_frame_chunker_emits_fixed_size() -> None:
    c = FrameChunker(4)
    assert c.push(b"ab") == []
    assert c.push(b"cdef") == [b"abcd"]
    assert c.push(b"gh") == [b"efgh"]


# ---- receiver PCM path ---------------------------------------------------


class _FakeLoop:
    """Runs call_soon_threadsafe inline so the test stays synchronous."""

    def call_soon_threadsafe(self, fn, *args):
        fn(*args)


def test_feed_pcm_mono_passthrough_not_downmixed() -> None:
    # discord-ext-voice-recv actually delivers 1920-byte (48k MONO) frames.
    # These must pass through untouched — averaging them as fake L/R pairs
    # was the 'muffled and garbled' bug (2:1 lowpass + doubled pitch).
    rec = DiscordVoiceReceiver(voice_client=None, loop=_FakeLoop())
    mono20ms = array.array("h", [8000] * 960).tobytes()  # 1920 bytes = mono 20ms
    rec.feed_pcm("u1", mono20ms)
    assert rec._channels == 1
    frame = rec._queue.get_nowait()
    assert frame.speaker_id == "u1"
    assert frame.pcm == mono20ms  # samples unchanged, not halved/averaged


def test_feed_pcm_stereo_is_downmixed() -> None:
    # If the decoder ever emits 3840-byte (48k STEREO) frames, downmix them.
    rec = DiscordVoiceReceiver(voice_client=None, loop=_FakeLoop())
    stereo20ms = array.array("h", [8000, 4000] * 960).tobytes()  # 3840 bytes = stereo 20ms
    rec.feed_pcm("u1", stereo20ms)
    assert rec._channels == 2
    frame = rec._queue.get_nowait()
    mono = array.array("h")
    mono.frombytes(frame.pcm)
    assert len(frame.pcm) == 1920 and all(s == 6000 for s in mono)  # (8000+4000)//2


def test_receiver_drops_while_not_capturing() -> None:
    rec = DiscordVoiceReceiver(voice_client=None, loop=_FakeLoop())
    rec.set_capturing(False)
    rec.feed_pcm("u1", array.array("h", [4096, 4096] * rec.bytes_per_frame).tobytes())
    assert rec._queue.empty()


# ---- wall-clock end-of-speech --------------------------------------------


def test_feed_pcm_arms_eos_on_voiced_frame() -> None:
    rec = DiscordVoiceReceiver(voice_client=None, loop=_FakeLoop())
    # Amplitude well above _SPEECH_FLOOR (1500): locks AND arms end-of-speech.
    stereo = array.array("h", [8000, 8000] * rec.bytes_per_frame).tobytes()
    rec.feed_pcm("u1", stereo)
    assert rec._active_speaker == "u1"
    assert rec._eos_armed is True


def test_eos_tick_flushes_after_voice_gap() -> None:
    rec = DiscordVoiceReceiver(voice_client=None, loop=_FakeLoop(), end_of_speech_s=0.7)
    # Speaker locked + last voiced at monotonic t=100.0.
    rec._active_speaker = "u1"
    rec._eos_armed = True
    rec._last_voice_ts = 100.0
    # Still within the gap → no flush.
    assert rec._eos_tick(100.5) is False
    assert rec._queue.empty()
    # Gap exceeded → flush marker enqueued, lock released so a new speaker
    # can take over.
    assert rec._eos_tick(100.8) is True
    frame = rec._queue.get_nowait()
    assert frame.flush is True and frame.speaker_id == "u1" and frame.pcm == b""
    assert rec._active_speaker is None and rec._eos_armed is False


def test_eos_tick_noop_when_unarmed_or_idle() -> None:
    rec = DiscordVoiceReceiver(voice_client=None, loop=_FakeLoop(), end_of_speech_s=0.5)
    # No active speaker at all.
    assert rec._eos_tick(1_000.0) is False
    # Locked but never voiced (only crossed the lock floor, not speech floor).
    rec._active_speaker = "u1"
    rec._eos_armed = False
    rec._last_voice_ts = 0.0
    assert rec._eos_tick(1_000.0) is False
    assert rec._queue.empty()


# ---- collaborator factories ----------------------------------------------


class _FakeSTT:
    def transcribe(self, path):
        assert Path(path).is_file()  # a real WAV was written
        return TranscribeResult(segments=[Segment(0, 1, "hello"), Segment(1, 2, "world")])


def test_make_transcribe_joins_segments() -> None:
    t = make_transcribe(_FakeSTT(), sample_rate=16_000)
    utt = Utterance(pcm=b"\x00\x00" * 200, sample_rate=16_000, speaker_id="u1")
    assert asyncio.run(t(utt)) == "hello world"


def test_make_transcribe_failure_returns_empty() -> None:
    class _Boom:
        def transcribe(self, path):
            raise RuntimeError("stt down")

    t = make_transcribe(_Boom())
    assert asyncio.run(t(Utterance(pcm=b"\x00\x00", sample_rate=16_000, speaker_id="u1"))) == ""


def test_make_speak_synthesizes_plays_and_cleans_up() -> None:
    played: list[Path] = []

    class _FakeTTS:
        def synthesize(self, text):
            fd, p = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            return SynthResult(path=Path(p), sample_rate=48_000, duration_s=1.0, backend="fake")

    async def _play(wav: Path) -> None:
        assert Path(wav).is_file()  # file exists during playback
        played.append(Path(wav))

    asyncio.run(make_speak(_play, _FakeTTS())("hi there"))
    assert len(played) == 1
    assert not played[0].exists()  # deleted after playback


# ---- run_turn reuses the gateway machinery -------------------------------


class _FakeAgent:
    def __init__(self, reply: str, model: str = "main-model") -> None:
        self._reply = reply
        self.seen: str | None = None
        self.model = model
        # Captured at run_until_done time so a test can assert which model
        # the turn actually ran under (the voice override is applied just
        # before the call and restored just after).
        self.model_during_turn: str | None = None

    def run_until_done(self, text: str) -> None:
        self.seen = text
        self.model_during_turn = self.model

    def last_assistant_message(self) -> str:
        return self._reply


class _FakeDaemon:
    def __init__(self, agent: _FakeAgent, voice_model: str = "") -> None:
        self._agent = agent

        class _Router:
            async def resolve(self, event):
                return "sess-1"

        class _Pool:
            def use(_self, sid):
                agent = self._agent

                class _Ctx:
                    async def __aenter__(self):
                        return agent

                    async def __aexit__(self, *a):
                        return False

                return _Ctx()

        self.router = _Router()
        self.pool = _Pool()
        self.cfg = SimpleNamespace(voice_model=voice_model)


def test_run_turn_routes_runs_and_returns_reply() -> None:
    agent = _FakeAgent("the answer")
    run_turn = make_voice_run_turn(_FakeDaemon(agent))
    event = MessageEvent(platform="discord", chat_id="c1", user_id="u1", text="what's up")
    reply = asyncio.run(run_turn(event))
    assert reply == "the answer"
    # The turn ran with the transcript (wrapped in the spoken-conversation
    # preamble so the model replies briefly + conversationally).
    assert agent.seen is not None and "what's up" in agent.seen
    assert "VOICE conversation" in agent.seen


def test_run_turn_applies_voice_model_override() -> None:
    # cfg.voice_model points voice turns at a fast model; the turn must run
    # under it, and the agent's model must be restored afterward so a shared
    # text session never inherits it.
    agent = _FakeAgent("ok", model="q35-thinking")
    run_turn = make_voice_run_turn(_FakeDaemon(agent, voice_model="fast:latest"))
    event = MessageEvent(platform="discord", chat_id="c1", user_id="u1", text="hi")
    asyncio.run(run_turn(event))
    assert agent.model_during_turn == "fast:latest"  # used during the turn
    assert agent.model == "q35-thinking"  # restored after


def test_run_turn_no_override_when_voice_model_empty() -> None:
    agent = _FakeAgent("ok", model="q35-thinking")
    run_turn = make_voice_run_turn(_FakeDaemon(agent, voice_model=""))
    event = MessageEvent(platform="discord", chat_id="c1", user_id="u1", text="hi")
    asyncio.run(run_turn(event))
    assert agent.model_during_turn == "q35-thinking"  # unchanged
    assert agent.model == "q35-thinking"
