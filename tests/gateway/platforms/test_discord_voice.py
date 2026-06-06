"""Discord voice plumbing — the voice tool surface and the collaborator
factories, all with fakes (no discord, no audio hardware).

The live receiver sink + FFmpeg playback need a real bot (the dogfood
runbook); everything reachable without discord is covered here.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from athena.audio.job import Segment, TranscribeResult
from athena.audio.tts import SynthResult
from athena.gateway.events import MessageEvent
from athena.gateway.platforms.discord_voice import (
    _VOICE_DISABLED_TOOLS,
    _VOICE_TOOLSETS,
    make_speak,
    make_transcribe,
    make_voice_run_turn,
)
from athena.gateway.voice.segmenter import Utterance

# ---- voice tool surface (progressive-disclosure skills) ------------------


def test_voice_surface_exposes_skills_read_only() -> None:
    # Voice enables the "skills" toolset so a spoken "list all skills" / "use
    # skill X" works — but only the READ tools. The mutation tool
    # (skill_manage) is excluded because a spoken session can't present its
    # confirmation gate. Full SKILL.md bodies still load on demand via
    # skill_view, never into the per-turn prompt.
    import athena.tools  # noqa: F401 — register the built-in tools
    from athena.tools.registry import all_tools

    assert "skills" in _VOICE_TOOLSETS
    assert "skill_manage" in _VOICE_DISABLED_TOOLS

    names = {
        t.name for t in all_tools(enabled_toolsets=_VOICE_TOOLSETS, disabled=_VOICE_DISABLED_TOOLS)
    }
    assert "skills_list" in names  # enumerate
    assert "skill_view" in names  # load one body on demand
    assert "skill_manage" not in names  # mutation kept off voice


def test_voice_surface_includes_task_tools() -> None:
    # The user opted into a full task surface: voice can run commands and
    # touch files. Assert the task toolsets are wired in and the command tool
    # actually resolves (it routes its approval to the Discord text channel).
    import athena.tools  # noqa: F401
    from athena.tools.registry import all_tools

    for ts in ("file", "shell", "code"):
        assert ts in _VOICE_TOOLSETS

    names = {
        t.name for t in all_tools(enabled_toolsets=_VOICE_TOOLSETS, disabled=_VOICE_DISABLED_TOOLS)
    }
    assert "Bash" in names  # run commands (incl. powershell -Command ...)
    assert "Write" in names or "write_file" in names  # create/edit files


# ---- collaborator factories ----------------------------------------------


class _FakeSTT:
    def transcribe(self, path, **kwargs):
        assert Path(path).is_file()  # a real WAV was written
        assert kwargs.get("language") == "en"  # voice pins language (M5)
        return TranscribeResult(segments=[Segment(0, 1, "hello"), Segment(1, 2, "world")])


def test_make_transcribe_joins_segments() -> None:
    t = make_transcribe(_FakeSTT(), sample_rate=16_000)
    utt = Utterance(pcm=b"\x00\x00" * 200, sample_rate=16_000, speaker_id="u1")
    assert asyncio.run(t(utt)) == "hello world"


def test_make_transcribe_failure_returns_empty() -> None:
    class _Boom:
        def transcribe(self, path, **kwargs):
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
