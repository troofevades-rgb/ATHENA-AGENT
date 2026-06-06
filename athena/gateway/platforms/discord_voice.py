"""Discord-specific voice wiring (Discord-voice Phase 3).

Bridges the platform-neutral voice core (``athena.gateway.voice``) to
Discord's APIs:

  - :class:`DiscordVoiceReceiver` adapts a ``discord-ext-voice-recv`` sink
    (48 kHz decoded PCM — mono for voice, though it can be stereo; the
    receiver detects which from the wire and downmixes only if needed,
    delivered on a capture thread) to the
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
import time
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


# Loudness floor (RMS of s16 mono) for picking the active speaker. Speech
# sits in the thousands; silence/keepalive near zero — 350 separates them.
_SPEAKER_LOCK_FLOOR = 350.0
# Energy above which a frame counts as the locked speaker's *voice* (vs
# room tone / breath / faint background). Higher than the lock floor: the
# lock only needs "someone is there", but end-of-speech needs "they are
# actually talking" so a quiet gap between sentences ends the turn. Tuned
# for Discord's 48 kHz s16 mono; speech runs ~5000-12000 RMS, room tone
# well under 1500.
_SPEECH_FLOOR = 1500.0


def _mono_rms(mono: bytes) -> float:
    """RMS amplitude of mono s16le bytes; 0.0 on empty."""
    s = array.array("h")
    s.frombytes(mono[: len(mono) - (len(mono) % 2)])
    if not s:
        return 0.0
    return (sum(x * x for x in s) / len(s)) ** 0.5


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

    def __init__(
        self,
        voice_client: Any,
        loop: asyncio.AbstractEventLoop,
        *,
        max_queue: int = 512,
        end_of_speech_s: float = 0.7,
        eos_poll_s: float = 0.1,
    ):
        self._vc = voice_client
        self._loop = loop
        self._queue: asyncio.Queue[VoiceFrame | None] = asyncio.Queue(maxsize=max_queue)
        self._chunkers: dict[str, FrameChunker] = {}
        self._capturing = True
        self._sink: Any = None
        # Single-active-speaker lock. voice-recv delivers a SEPARATE decoded
        # stream per speaker (including the bot's own silence keepalive).
        # Interleaving them into one segmenter scrambles the audio timeline
        # into garbage. We lock onto whoever is actively talking (loudest
        # first) and ignore everyone else until they fall quiet.
        self._active_speaker: str | None = None
        self._silence_bytes = 0
        # ~1.2s of mono silence releases the lock so a different speaker can
        # take over. 48000 Hz * 2 bytes.
        self._release_silence_bytes = int(1.2 * 48_000 * 2)
        # End-of-speech (wall clock). The segmenter ends an utterance on a
        # run of VAD-silence, but in an open-mic channel the VAD may never
        # see silence (continuous background) — so the turn rides to the max
        # cap. Here we watch the clock instead: once the active speaker's
        # *voice* (>= _SPEECH_FLOOR) has been absent for end_of_speech_s, a
        # watcher injects a flush marker that closes the utterance now. Works
        # even when Discord stops sending packets entirely on silence (no
        # frames => the frame-counted segmenter would otherwise stall).
        self._end_of_speech_s = float(end_of_speech_s)
        self._eos_poll_s = float(eos_poll_s)
        self._last_voice_ts = 0.0  # monotonic; last frame >= _SPEECH_FLOOR
        self._eos_armed = False  # True once the active speaker has voiced
        self._eos_task: asyncio.Task[None] | None = None
        # Decoded channel count, detected from the wire (see feed_pcm). The
        # discord.opus.Decoder class advertises stereo, but this voice-recv
        # build decodes MONO for voice — trusting the constant and averaging
        # "L/R pairs" lowpassed the audio and doubled its pitch.
        self._channels: int | None = None

    # Called on the capture thread. Pure-ish: convert + enqueue. Exposed
    # (not underscored away) so tests can drive it directly with a fake loop.
    def feed_pcm(self, speaker_id: str, pcm: bytes) -> None:
        if not self._capturing:
            return
        # Discord delivers one 20 ms decoded frame per packet: 1920 bytes =
        # 48 kHz mono, 3840 = 48 kHz stereo. Detect the layout from the wire
        # once (the Decoder class lies — it says stereo but emits mono here),
        # then downmix ONLY when it's genuinely stereo. Treating mono as
        # stereo averaged adjacent samples → muffled + 2x pitch = garbage.
        if self._channels is None and len(pcm) in (1920, 3840):
            self._channels = 2 if len(pcm) == 3840 else 1
            logger.info("discord voice: decode is %d-channel (%dB/frame)", self._channels, len(pcm))
        mono = stereo_to_mono(pcm) if self._channels == 2 else pcm
        if not mono:
            return

        # Single-active-speaker lock — forward only one speaker's audio so
        # the segmenter never sees an interleaved mix (the garbage bug).
        sid = str(speaker_id)
        rms = _mono_rms(mono)
        loud = rms >= _SPEAKER_LOCK_FLOOR
        if self._active_speaker is None:
            if not loud:
                return  # nobody talking yet — don't lock onto silence
            self._active_speaker = sid
            self._silence_bytes = 0
            self._eos_armed = False
        elif sid != self._active_speaker:
            return  # someone else (or the bot's keepalive) — ignore while locked
        if loud:
            self._silence_bytes = 0
        else:
            self._silence_bytes += len(mono)
            if self._silence_bytes >= self._release_silence_bytes:
                self._active_speaker = None  # released; re-lock on next loud speaker
        # Track the last moment this speaker was actually *voicing* (not just
        # above the lock floor) so the wall-clock watcher can find the gap.
        if rms >= _SPEECH_FLOOR:
            self._last_voice_ts = time.monotonic()
            self._eos_armed = True

        chunker = self._chunkers.setdefault(sid, FrameChunker(self.bytes_per_frame))
        for frame_pcm in chunker.push(mono):
            frame = VoiceFrame(speaker_id=sid, pcm=frame_pcm)
            self._loop.call_soon_threadsafe(self._enqueue, frame)

    def _eos_tick(self, now: float) -> bool:
        """One end-of-speech check at wall-clock ``now`` (monotonic).

        If the active speaker has voiced and then stayed below the speech
        floor for ``end_of_speech_s``, enqueue a flush marker and release the
        lock so the next speaker can take over. Returns True iff it flushed.
        Pure enough to unit-test directly; the watcher loop just feeds it
        ``time.monotonic()``. Runs on the event loop, so it enqueues directly
        (no call_soon_threadsafe — that's for the capture thread)."""
        if self._active_speaker is None or not self._eos_armed:
            return False
        if now - self._last_voice_ts < self._end_of_speech_s:
            return False
        speaker = self._active_speaker
        self._eos_armed = False
        self._active_speaker = None
        self._silence_bytes = 0
        logger.info(
            "discord voice: end-of-speech (%.1fs quiet) — flushing utterance",
            self._end_of_speech_s,
        )
        self._enqueue(VoiceFrame(speaker_id=speaker, pcm=b"", flush=True))
        return True

    async def _eos_watcher(self) -> None:
        """Poll :meth:`_eos_tick` until the receiver stops. Cancelled in
        :meth:`stop`. A watcher fault must not kill capture — it's logged and
        the loop continues."""
        while True:
            await asyncio.sleep(self._eos_poll_s)
            try:
                self._eos_tick(time.monotonic())
            except Exception as e:  # noqa: BLE001 — never let the watcher die silently
                logger.debug("discord voice: eos watcher tick failed: %s", e)

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
        # Wall-clock end-of-speech watcher (see feed_pcm / _eos_tick).
        self._eos_task = asyncio.create_task(self._eos_watcher())

    async def stop(self) -> None:
        if self._eos_task is not None:
            self._eos_task.cancel()
            self._eos_task = None
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
            # Operational log: transcript + signal level (silence vs speech)
            # and duration — cheap, and the first thing to check when a turn
            # doesn't land.
            rms = int(_mono_rms(utterance.pcm))
            logger.info(
                "discord voice: heard %r (%.1fs, rms=%d)", text[:200], utterance.duration_s, rms
            )
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
            # Voice model override (cfg.voice_model): this chat model may be
            # a thinking model whose <think> block costs ~12-20s per spoken
            # reply (stripped from speech, but still generated). Pointing
            # voice at a fast non-thinking model keeps turns snappy while the
            # main `model` stays the coding brain. Same Ollama provider, so
            # swapping the model string is the whole switch (cf.
            # commands/model._switch_model). Restored in finally so a text
            # session sharing this pooled agent never inherits the voice model.
            saved_model = None
            voice_model = (getattr(daemon.cfg, "voice_model", "") or "").strip()
            if voice_model and voice_model != agent.model:
                saved_model = agent.model
                agent.model = voice_model
            # The model is in a SPOKEN conversation: the user message was
            # transcribed (may have errors) and the reply will be read
            # aloud. Without this it answers like a CLI text query — long,
            # markdown-formatted, easily derailed by a noisy transcript.
            user_text = f"{VOICE_TURN_PREAMBLE}\n\n{event.text}"
            try:
                await asyncio.to_thread(agent.run_until_done, user_text)
            finally:
                if saved_model is not None:
                    agent.model = saved_model
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
