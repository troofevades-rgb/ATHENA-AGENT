"""Discord-specific voice wiring (Discord-voice Phase 3).

Bridges the platform-neutral voice core (``athena.gateway.voice``) to
Discord's APIs:

  - :class:`DiscordVoiceReceiver` adapts a ``discord-ext-voice-recv`` sink
    (48 kHz stereo PCM, delivered on a capture thread) to the
    :class:`~athena.gateway.voice.VoiceReceiver` contract (mono frames on
    an asyncio queue).
  - the collaborator factories (:func:`make_transcribe`, :func:`make_speak`,
    :func:`make_voice_run_turn`) build the ``transcribe`` / ``speak`` /
    ``run_turn`` callables the :class:`VoiceSession` is injected with — the
    turn runner reuses the gateway's session routing, agent pool, and
    Discord-button approval bridge, so a voice turn is indistinguishable
    from a text turn downstream.

Every ``discord`` / ``voice_recv`` import is lazy (inside the functions
that need them), so this module imports cleanly without the optional
``[gateway-voice]`` deps installed — the pure conversion helpers and the
collaborator factories are unit-tested with fakes; the live receiver +
FFmpeg playback need a real bot (the dogfood runbook).
"""

from __future__ import annotations

import array
import asyncio
import logging
import os
import tempfile
import wave
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from ..events import MessageEvent
from ..voice import VoiceFrame, VoiceReceiver
from ..voice.segmenter import Utterance
from ..voice.session import RunTurnFn, SpeakFn, TranscribeFn

logger = logging.getLogger(__name__)

PlayFn = Callable[[Path], Awaitable[None]]

# Prepended to every voice turn so the model knows it's a *spoken*
# conversation (transcribed input, spoken-aloud output) and replies
# accordingly — short, plain, conversational.
VOICE_TURN_PREAMBLE = (
    "[You are in a live VOICE conversation. The message below was transcribed "
    "from the user's speech and may contain recognition errors — infer intent "
    "charitably. Your reply will be read aloud by text-to-speech, so answer in "
    "one or two short, natural spoken sentences: no markdown, no lists, no code "
    "blocks, no emoji. If you truly need a tool, use it, but keep talking like a "
    "person.]"
)

# Set once we've patched discord-ext-voice-recv's fatal Opus handling.
_opus_resilience_installed = False


def install_opus_resilience() -> None:
    """Make ``discord-ext-voice-recv`` survive a corrupted Opus packet.

    Its ``PacketRouter`` loop has **no per-packet error handling**: a single
    ``OpusError: corrupted stream`` (Discord sends odd/comfort-noise packets)
    escapes the loop and the router's ``finally`` calls ``stop_listening()``,
    permanently deafening the session. We wrap the decoder's ``pop_data`` to
    swallow ``OpusError`` and skip the bad packet (return ``None``) so the
    loop keeps running. Idempotent; a no-op if the library's shape changes
    (logged, never fatal). Targeted workaround for the 0.5.x alpha.
    """
    global _opus_resilience_installed
    if _opus_resilience_installed:
        return
    try:
        from discord.ext.voice_recv import opus as _vr_opus
        from discord.opus import OpusError

        _orig_pop = _vr_opus.PacketDecoder.pop_data

        def _safe_pop_data(self: Any, *args: Any, **kwargs: Any) -> Any:
            try:
                return _orig_pop(self, *args, **kwargs)
            except OpusError:
                logger.debug("discord voice: skipped a corrupted Opus packet")
                return None

        # Direct assignment (mypy flags method-assign only when voice_recv
        # is installed locally; CI sees it as Any → clean. ruff rejects
        # setattr-with-constant, so this is the lint-clean form).
        _vr_opus.PacketDecoder.pop_data = _safe_pop_data  # type: ignore[method-assign,unused-ignore]
        _opus_resilience_installed = True
        logger.info("discord voice: installed Opus decode resilience")
    except Exception as e:  # noqa: BLE001
        logger.warning("discord voice: could not install Opus resilience: %s", e)


# ---- pure audio helpers (no discord) -------------------------------------


def stereo_to_mono(pcm_stereo: bytes) -> bytes:
    """Downmix interleaved 16-bit L/R PCM to mono by averaging each pair.

    Discord delivers 48 kHz stereo; the voice core works in mono. A stray
    tail that isn't a whole L/R sample pair (4 bytes) is dropped rather
    than raising.
    """
    usable = pcm_stereo[: len(pcm_stereo) - (len(pcm_stereo) % 4)]
    if not usable:
        return b""
    stereo = array.array("h")
    stereo.frombytes(usable)
    mono = array.array("h", [(stereo[i] + stereo[i + 1]) // 2 for i in range(0, len(stereo), 2)])
    return mono.tobytes()


class FrameChunker:
    """Accumulate PCM bytes and emit fixed-size frames.

    Voice backends deliver variable-size buffers; the segmenter needs
    uniform frames. Per-speaker so concurrent speakers don't interleave
    into one chunk.
    """

    def __init__(self, bytes_per_frame: int) -> None:
        self._n = int(bytes_per_frame)
        self._buf = bytearray()

    def push(self, pcm: bytes) -> list[bytes]:
        self._buf += pcm
        out: list[bytes] = []
        while self._n > 0 and len(self._buf) >= self._n:
            out.append(bytes(self._buf[: self._n]))
            del self._buf[: self._n]
        return out


# ---- receiver ------------------------------------------------------------


class DiscordVoiceReceiver(VoiceReceiver):
    """Adapts a discord-ext-voice-recv sink to :class:`VoiceReceiver`.

    The sink's ``write`` runs on discord.py's capture thread; we downmix +
    chunk there and hand frames to the asyncio loop via
    ``call_soon_threadsafe``. ``frames()`` then drains an
    :class:`asyncio.Queue`. A ``None`` sentinel from :meth:`stop` ends the
    stream cleanly.
    """

    sample_rate = 48_000
    frame_ms = 20

    def __init__(self, voice_client: Any, loop: asyncio.AbstractEventLoop, *, max_queue: int = 512):
        self._vc = voice_client
        self._loop = loop
        self._queue: asyncio.Queue[VoiceFrame | None] = asyncio.Queue(maxsize=max_queue)
        self._chunkers: dict[str, FrameChunker] = {}
        self._capturing = True
        self._sink: Any = None

    # Called on the capture thread. Pure-ish: convert + enqueue. Exposed
    # (not underscored away) so tests can drive it directly with a fake loop.
    def feed_pcm(self, speaker_id: str, pcm_stereo: bytes) -> None:
        if not self._capturing:
            return
        mono = stereo_to_mono(pcm_stereo)
        if not mono:
            return
        chunker = self._chunkers.setdefault(str(speaker_id), FrameChunker(self.bytes_per_frame))
        for frame_pcm in chunker.push(mono):
            frame = VoiceFrame(speaker_id=str(speaker_id), pcm=frame_pcm)
            self._loop.call_soon_threadsafe(self._enqueue, frame)

    def _enqueue(self, frame: VoiceFrame | None) -> None:
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            # Back-pressure safety valve: drop the oldest frame. A voice
            # turn cares about recent audio, not a stale backlog.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(frame)
            except Exception:  # noqa: BLE001
                pass

    def set_capturing(self, on: bool) -> None:
        self._capturing = on

    async def start(self) -> None:
        from discord.ext import voice_recv  # optional dep

        install_opus_resilience()  # one bad packet must not deafen the session
        receiver = self

        class _Sink(voice_recv.AudioSink):  # type: ignore[misc,unused-ignore]
            def wants_opus(self) -> bool:
                return False  # we want decoded PCM

            def write(self, user: Any, data: Any) -> None:
                receiver.feed_pcm(getattr(user, "id", "unknown"), data.pcm)

            def cleanup(self) -> None:
                return None

        self._sink = _Sink()
        self._vc.listen(self._sink)

    async def stop(self) -> None:
        try:
            if self._vc is not None:
                self._vc.stop_listening()
        except Exception as e:  # noqa: BLE001
            logger.debug("discord voice: stop_listening raised: %s", e)
        self._enqueue(None)  # unblock frames()

    async def frames(self) -> AsyncIterator[VoiceFrame]:
        while True:
            frame = await self._queue.get()
            if frame is None:
                break
            yield frame


# ---- playback ------------------------------------------------------------


async def play_wav_in_vc(
    voice_client: Any, wav_path: Path, *, loop: asyncio.AbstractEventLoop
) -> None:
    """Play a WAV into the voice channel and await completion."""
    import discord  # lazy

    done = asyncio.Event()

    def _after(_err: Exception | None) -> None:
        loop.call_soon_threadsafe(done.set)

    source = discord.FFmpegPCMAudio(str(wav_path))
    voice_client.play(source, after=_after)
    await done.wait()


# ---- collaborator factories ----------------------------------------------


def make_transcribe(stt_backend: Any, *, sample_rate: int = 48_000) -> TranscribeFn:
    """Build the ``transcribe`` collaborator: utterance PCM → text.

    Writes the mono PCM to a temp WAV, runs the (blocking) STT backend
    off-thread, joins its segments, and deletes the temp file. A
    transcription failure returns ``""`` (the session treats that as
    "nothing intelligible" and stays listening) rather than raising.
    """

    async def transcribe(utterance: Utterance) -> str:
        fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="athena_voice_")
        os.close(fd)
        path = Path(tmp)
        try:
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(utterance.pcm)
            result = await asyncio.to_thread(stt_backend.transcribe, path)
            text = " ".join(seg.text for seg in result.segments).strip()
            logger.info("discord voice: heard %r (%.1fs audio)", text[:200], utterance.duration_s)
            return text
        except Exception as e:  # noqa: BLE001
            logger.warning("discord voice: transcription failed: %s", e)
            return ""
        finally:
            path.unlink(missing_ok=True)

    return transcribe


def make_speak(play: PlayFn, tts_backend: Any, *, voice: str | None = None) -> SpeakFn:
    """Build the ``speak`` collaborator: text → synthesize → play → cleanup."""

    async def speak(text: str) -> None:
        logger.info("discord voice: speaking %r", text[:200])
        result = await asyncio.to_thread(tts_backend.synthesize, text)
        out = Path(result.path)
        try:
            await play(out)
            logger.info("discord voice: playback done (%.1fs)", result.duration_s)
        except Exception:
            logger.exception("discord voice: playback failed")
            raise
        finally:
            out.unlink(missing_ok=True)

    return speak


def make_voice_run_turn(daemon: Any, *, approval_timeout: float = 300.0) -> RunTurnFn:
    """Build the ``run_turn`` collaborator: a voice utterance → agent turn
    → reply text, reusing the gateway's own machinery.

    Same path a text turn takes: ``router.resolve`` → ``pool.use`` →
    ``run_until_done`` → ``last_assistant_message``. The Discord-button
    approval bridge is installed for the turn so a tool confirmation routes
    to the text channel exactly as it does for text (best-effort: if the
    bridge can't be built the turn still runs, just without it).
    """
    from ...safety.approval_callback import reset_approval_callback, set_approval_callback
    from ...text_utils import strip_think_blocks
    from ..agent_factory import build_gateway_approval_callback

    async def run_turn(event: MessageEvent) -> str:
        session_id = await daemon.router.resolve(event)
        async with daemon.pool.use(session_id) as agent:
            token = None
            try:
                cb = build_gateway_approval_callback(
                    daemon,
                    session_id=session_id,
                    platform=event.platform,
                    chat_id=event.chat_id,
                    timeout=approval_timeout,
                )
                token = set_approval_callback(cb)
            except Exception as e:  # noqa: BLE001
                logger.debug("discord voice: approval bridge unavailable: %s", e)
            # The model is in a SPOKEN conversation: the user message was
            # transcribed (may have errors) and the reply will be read
            # aloud. Without this it answers like a CLI text query — long,
            # markdown-formatted, easily derailed by a noisy transcript.
            user_text = f"{VOICE_TURN_PREAMBLE}\n\n{event.text}"
            try:
                await asyncio.to_thread(agent.run_until_done, user_text)
            finally:
                if token is not None:
                    reset_approval_callback(token)
            reply = strip_think_blocks(agent.last_assistant_message()).strip()
            logger.info("discord voice: reply %r", reply[:200])
            return reply

    return run_turn


# ---- STT resolution + session assembly -----------------------------------


def _resolve_stt(cfg: Any) -> Any | None:
    """The audio-transcription backend via the capability broker, or None
    when none is available (graceful degrade — voice reports unavailable)."""
    from ...audio import backends  # noqa: F401 — registration side effect
    from ...media.registry import MediaRegistry

    cls = MediaRegistry(cfg=cfg).backend_for("audio_transcription")
    if cls is None:
        return None
    try:
        inst = cls()
    except Exception as e:  # noqa: BLE001
        logger.warning("discord voice: STT backend construct failed: %s", e)
        return None
    ok = hasattr(inst, "transcribe") and getattr(inst, "is_available", lambda: True)()
    return inst if ok else None


class DiscordVoiceController:
    """Owns the single active voice session for one DiscordAdapter.

    One session per adapter (per bot connection) in v1 — ``join`` refuses
    while a session is live. Assembles the platform-neutral
    :class:`VoiceSession` from a connected voice client + the resolved STT
    / TTS backends, wires the gateway turn runner, and posts the consent
    notice. All graceful: a missing STT / TTS / voice-recv dep yields a
    spoken-in-text "voice unavailable" rather than an exception.
    """

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter
        self._vc: Any = None
        self._session: Any = None
        self._task: asyncio.Task[Any] | None = None

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    def grant_consent(self) -> bool:
        if self._session is None:
            return False
        self._session.grant_consent()
        return True

    async def join(self, voice_channel: Any, text_chat_id: str, cfg: Any) -> str:
        if self.active:
            return "Already in a voice channel — `/voice leave` first."

        stt = _resolve_stt(cfg)
        if stt is None:
            return "Voice unavailable: no speech-to-text backend (install the audio extra)."
        from ...audio.tts import resolve_tts_backend

        tts = resolve_tts_backend(cfg)
        if tts is None:
            return (
                "Voice unavailable: no text-to-speech backend. Install `[tts]` "
                "and set `tts_voice` to a Piper `.onnx` voice."
            )

        try:
            from discord.ext import voice_recv  # optional dep

            self._vc = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
        except Exception as e:  # noqa: BLE001
            logger.warning("discord voice: connect failed: %s", e)
            return f"Couldn't join voice: {e}"

        loop = asyncio.get_running_loop()
        receiver = DiscordVoiceReceiver(self._vc, loop)

        async def _play(wav: Path) -> None:
            await play_wav_in_vc(self._vc, wav, loop=loop)

        from ..voice import VoiceSession, VoiceSessionConfig

        config = VoiceSessionConfig(platform=self._adapter.name, chat_id=str(text_chat_id))
        self._session = VoiceSession(
            receiver=receiver,
            transcribe=make_transcribe(stt),
            run_turn=make_voice_run_turn(self._adapter.daemon),
            speak=make_speak(_play, tts),
            config=config,
        )

        notice = (
            "🎙️ Athena is in the voice channel and **will transcribe what's said**. "
            "Run `/voice consent` to begin, or `/voice leave` to end."
            if config.require_consent
            else "🎙️ Athena is now listening. `/voice leave` to end."
        )
        await self._adapter.send_text(str(text_chat_id), notice)
        if not config.require_consent:
            self._session.grant_consent()

        self._task = asyncio.create_task(self._session.run(), name="discord-voice-session")
        return "Joined voice."

    async def leave(self) -> str:
        if not self.active and self._vc is None:
            return "Not in a voice channel."
        if self._session is not None:
            self._session.request_stop()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except Exception:  # noqa: BLE001 — best-effort drain
                self._task.cancel()
        try:
            if self._vc is not None:
                await self._vc.disconnect()
        except Exception as e:  # noqa: BLE001
            logger.debug("discord voice: disconnect raised: %s", e)
        self._vc = self._session = self._task = None
        return "Left voice."
