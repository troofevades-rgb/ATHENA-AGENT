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


def test_receiver_feed_pcm_converts_and_enqueues() -> None:
    rec = DiscordVoiceReceiver(voice_client=None, loop=_FakeLoop())
    # Enough stereo audio for at least one mono frame.
    stereo = array.array("h", [4096, 4096] * (rec.bytes_per_frame)).tobytes()
    rec.feed_pcm("u1", stereo)
    assert not rec._queue.empty()
    frame = rec._queue.get_nowait()
    assert frame.speaker_id == "u1"
    assert len(frame.pcm) == rec.bytes_per_frame


def test_receiver_drops_while_not_capturing() -> None:
    rec = DiscordVoiceReceiver(voice_client=None, loop=_FakeLoop())
    rec.set_capturing(False)
    rec.feed_pcm("u1", array.array("h", [4096, 4096] * rec.bytes_per_frame).tobytes())
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
    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.seen: str | None = None

    def run_until_done(self, text: str) -> None:
        self.seen = text

    def last_assistant_message(self) -> str:
        return self._reply


class _FakeDaemon:
    def __init__(self, agent: _FakeAgent) -> None:
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
