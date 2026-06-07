"""Discord-specific voice wiring (Discord-voice Phase 3).

Bridges the platform-neutral voice core (``athena.gateway.voice``) to
Discord's APIs:

  - the live receiver is :class:`HermesVoiceReceiver` (raw-UDP capture +
    DAVE decrypt + Opus decode) in ``_hermes_voice_recv``, driven by
    :class:`HermesVoiceSession`, which polls complete utterances.
  - the collaborator factories (:func:`make_transcribe`, :func:`make_speak`,
    :func:`make_voice_run_turn`) build the ``transcribe`` / ``speak`` /
    ``run_turn`` callables the :class:`VoiceSession` is injected with — the
    turn runner reuses the gateway's session routing, agent pool, and
    Discord-button approval bridge, so a voice turn is indistinguishable
    from a text turn downstream.

Every ``discord`` import is lazy (inside the functions
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
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ..events import MessageEvent, MessageType
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
    "blocks, no emoji. If the user asks what you can do, what skills you have, "
    "or to use/run a skill, call the skills_list or skill_view tool instead of "
    "guessing (then summarise the result aloud); use other tools too when you "
    "genuinely need them. Otherwise just keep talking like a person.]"
)

# Context window for voice turns. Smaller than the coding default (32k) so the
# voice model's KV cache fits fully on the GPU instead of spilling to CPU —
# the difference between ~1-2s and multi-minute spoken replies. Holds the
# system prompt plus a spoken exchange.
_VOICE_CONTEXT_WINDOW = 16384

# Tool surface for voice turns. Scopes ONLY the dedicated voice agent's cfg
# (coding keeps all tools). Beyond the conversational set (core/memory/recall/
# web) and "skills" (on-demand list/invoke — progressive disclosure keeps only
# the one-line catalog in the prompt, bodies load via skill_view), this
# includes the TASK surface (file, shell, code) so a spoken "run the tests" /
# "edit X" actually executes. The user opted into this fuller surface over a
# lean talk-only set, accepting the trade-off: more tool schemas = larger
# prompt eval per spoken turn. Confirmation-gated tools (e.g. Bash) route their
# Approve/Deny prompt to the Discord text channel via the gateway approval
# bridge. NOTE: athena's shell tool is Bash (Git Bash on Windows); a PowerShell
# command runs as Bash("powershell -Command '...'").
_VOICE_TOOLSETS = ["core", "memory", "recall", "web", "skills", "file", "shell", "code"]

# Tools removed from the voice surface even though their toolset is enabled.
# skill_manage mutates skills behind a confirmation gate, and a spoken session
# has no interactive surface to present that gate (a forked AUTO_DENY callback
# would just block it) — so keep voice skills read-only: list + view.
_VOICE_DISABLED_TOOLS = ["skill_manage"]

# Keep the voice model resident between spoken turns (Ollama unloads after 5
# min idle by default, which would cost a full reload on the next utterance).
_VOICE_KEEP_ALIVE = "30m"

# ---- pure audio helpers (no discord) -------------------------------------


def _mono_rms(mono: bytes) -> float:
    """RMS amplitude of mono s16le bytes; 0.0 on empty."""
    s = array.array("h")
    s.frombytes(mono[: len(mono) - (len(mono) % 2)])
    if not s:
        return 0.0
    return float((sum(x * x for x in s) / len(s)) ** 0.5)


def downmix_stereo_to_mono(pcm_stereo: bytes) -> bytes:
    """Average interleaved 16-bit L/R PCM to mono. The Hermes receiver
    decodes Discord voice to genuine 48 kHz stereo; whisper wants mono.
    (Unlike the removed ``stereo_to_mono``, this runs on *real* stereo —
    the earlier bug was applying a downmix to data that was already mono.)"""
    a = array.array("h")
    a.frombytes(pcm_stereo[: len(pcm_stereo) - (len(pcm_stereo) % 4)])
    if not a:
        return b""
    mono = array.array("h", [(a[i] + a[i + 1]) // 2 for i in range(0, len(a), 2)])
    return mono.tobytes()


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


def make_transcribe(
    stt_backend: Any, *, sample_rate: int = 48_000, language: str | None = "en"
) -> TranscribeFn:
    """Build the ``transcribe`` collaborator: utterance PCM → text.

    Writes the mono PCM to a temp WAV, runs the (blocking) STT backend
    off-thread, joins its segments, and deletes the temp file. A
    transcription failure returns ``""`` (the session treats that as
    "nothing intelligible" and stays listening) rather than raising.

    ``language`` is pinned ("en" by default) so whisper doesn't re-detect the
    language on every short utterance — re-detection is both slower and a
    common source of wrong-language gibberish on brief/quiet clips.
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
            result = await asyncio.to_thread(stt_backend.transcribe, path, language=language)
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
            # Best-effort: on Windows FFmpeg can still hold the handle for a
            # beat after playback ends (WinError 32). Don't let a failed temp
            # cleanup surface as a "turn failed".
            try:
                out.unlink(missing_ok=True)
            except OSError:
                pass

    return speak


def make_voice_run_turn(
    daemon: Any, *, session_id: str | None = None, approval_timeout: float = 300.0
) -> RunTurnFn:
    """Build the ``run_turn`` collaborator: a voice utterance → agent turn
    → reply text, reusing the gateway's own machinery.

    ``run_until_done`` → ``last_assistant_message``. The Discord-button
    approval bridge is installed for the turn so a tool confirmation routes
    to the text channel exactly as it does for text (best-effort: if the
    bridge can't be built the turn still runs, just without it).

    ``session_id``: pin voice turns to a dedicated session instead of
    ``router.resolve``-ing the text channel's. Voice should NOT inherit a
    long-lived text session's history (tens of turns → tens of thousands of
    tokens → a multi-second context-compression on every spoken reply). A
    fresh per-join id keeps voice snappy and self-contained; approvals still
    route to the real ``event.chat_id``.
    """
    from ...safety.approval_callback import reset_approval_callback, set_approval_callback
    from ...text_utils import strip_think_blocks
    from ..agent_factory import build_gateway_approval_callback

    async def run_turn(event: MessageEvent) -> str:
        sid = session_id or await daemon.router.resolve(event)
        return await _run(event, sid)

    async def _run(event: MessageEvent, session_id: str) -> str:
        async with daemon.pool.use(session_id) as agent:
            # What model will this voice turn actually run? cfg.voice_model
            # overrides the agent's main model; empty → the main model. Resolve
            # it BEFORE cfg-tuning to decide whether to shrink the context: a
            # smaller num_ctx forces Ollama to load a SEPARATE model instance,
            # so when voice shares the main/coder model we must keep its context
            # to reuse the already-warm instance — otherwise every voice↔coding
            # switch reloads a multi-GB model.
            voice_model = (getattr(daemon.cfg, "voice_model", "") or "").strip()
            runs_main_model = (not voice_model) or (voice_model == getattr(agent, "model", None))

            # Voice-tune the agent's cfg ONCE (idempotent) via a private copy
            # (dataclasses.replace) so coding keeps its full context + all tools:
            #  - enabled_toolsets → a lean conversational set (+ "skills" for
            #    on-demand list/invoke): the full ~60 tool schemas are ~11.5k
            #    tokens that dominate prompt eval; a spoken chat rarely needs
            #    file/shell/code.
            #  - context_window → 16k ONLY when voice runs a DISTINCT model
            #    (e.g. a dedicated fast voice model that would spill to CPU at
            #    32k). When voice shares the main/coder model, leave the context
            #    untouched so the warm instance is reused (no reload thrash).
            cfg = getattr(agent, "cfg", None)
            if cfg is not None:
                try:
                    import dataclasses

                    cur_ctx = (
                        getattr(cfg, "context_window", _VOICE_CONTEXT_WINDOW)
                        or _VOICE_CONTEXT_WINDOW
                    )
                    new_ctx = cur_ctx if runs_main_model else min(cur_ctx, _VOICE_CONTEXT_WINDOW)
                    disabled = sorted(
                        set(getattr(cfg, "disabled_tools", None) or []) | set(_VOICE_DISABLED_TOOLS)
                    )
                    agent.cfg = dataclasses.replace(
                        agent.cfg,
                        context_window=new_ctx,
                        enabled_toolsets=list(_VOICE_TOOLSETS),
                        ollama_keep_alive=_VOICE_KEEP_ALIVE,
                        disabled_tools=disabled,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.debug("discord voice: could not voice-tune cfg: %s", e)
            # Voice is a CONVERSATION, not autonomous task pursuit. Strip the
            # persisted /goal so the agent replies to the spoken input instead
            # of running the goal continuation loop (turn N/10000) toward the
            # global goal, and rebuild the system prompt against the voice cfg.
            # Defensive getattr so test fakes without these attrs are unaffected.
            if getattr(agent, "goal", None) is not None or getattr(agent, "goal_state", None):
                try:
                    agent.goal = None
                    agent.goal_state = None
                    msgs = getattr(agent, "messages", None)
                    if msgs and msgs[0].get("role") == "system" and hasattr(agent, "_build_system"):
                        msgs[0] = {"role": "system", "content": agent._build_system()}
                except Exception as e:  # noqa: BLE001
                    logger.debug("discord voice: could not clear goal: %s", e)
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


class HermesVoiceSession:
    """Poll-based voice session over the raw-socket Hermes receiver.

    Replaces the frames()+segmenter path for Discord. The Hermes receiver
    captures + decrypts + decodes + silence-segments per speaker and hands
    back complete utterances via ``check_silence()`` (48 kHz stereo PCM). We
    poll it, then run the SAME transcribe → agent-turn → speak collaborators
    a text turn uses. Half-duplex: capture is paused while Athena speaks so
    she can't transcribe her own TTS.
    """

    def __init__(
        self,
        *,
        receiver: Any,
        transcribe: TranscribeFn,
        run_turn: RunTurnFn,
        speak: SpeakFn,
        platform: str,
        chat_id: str,
        require_consent: bool = True,
        poll_interval_s: float = 0.2,
    ) -> None:
        self.receiver = receiver
        self._transcribe = transcribe
        self._run_turn = run_turn
        self._speak = speak
        self._platform = platform
        self._chat_id = chat_id
        self._consent = not require_consent
        self._poll_interval_s = poll_interval_s
        self._stop = False

    def grant_consent(self) -> None:
        self._consent = True
        # Capture is paused until consent (see run()); resume it now.
        try:
            self.receiver.resume()
        except Exception as e:  # noqa: BLE001
            logger.debug("discord voice: resume on consent failed: %s", e)

    def request_stop(self) -> None:
        self._stop = True

    async def run(self) -> None:
        try:
            self.receiver.start()  # sync: installs UDP listener + SPEAKING hook
        except Exception as e:  # noqa: BLE001
            logger.warning("discord voice: receiver start failed: %s", e)
            return
        # CONSENT GATE: do NOT capture/decrypt/buffer anyone's audio until the
        # user runs /voice consent. _on_packet early-returns while paused
        # (before any NaCl/DAVE decrypt), so pausing here means nothing is
        # recorded pre-consent — matching the "run /voice consent to begin"
        # notice (previously the receiver decrypted + buffered immediately).
        if not self._consent:
            self.receiver.pause()
        try:
            while not self._stop:
                await asyncio.sleep(self._poll_interval_s)
                if not self._consent:
                    continue
                try:
                    utterances = self.receiver.check_silence()
                except Exception as e:  # noqa: BLE001
                    logger.debug("discord voice: check_silence raised: %s", e)
                    continue
                for user_id, pcm_stereo in utterances:
                    await self._handle(str(user_id), pcm_stereo)
        finally:
            try:
                self.receiver.stop()
            except Exception as e:  # noqa: BLE001
                logger.debug("discord voice: receiver stop raised: %s", e)

    async def _handle(self, user_id: str, pcm_stereo: bytes) -> None:
        # Pause capture while transcribing + thinking so we don't pile more
        # audio onto this turn. RESUME before speaking so the user can barge
        # in: the receiver's on_voice_activity hook stops playback the instant
        # they start talking (see the barge callback wired in join()).
        self.receiver.pause()
        try:
            mono = downmix_stereo_to_mono(pcm_stereo)
            if not mono:
                return
            utterance = Utterance(pcm=mono, sample_rate=48_000, speaker_id=user_id)
            text = (await self._transcribe(utterance)).strip()
            if not text:
                return
            event = MessageEvent(
                platform=self._platform,
                chat_id=self._chat_id,
                user_id=user_id,
                text=text,
                message_type=MessageType.AUDIO,
                is_dm=False,
                raw={"voice": True, "duration_s": round(len(mono) / (48_000 * 2), 3)},
            )
            reply = (await self._run_turn(event) or "").strip()
            if reply:
                self.receiver.resume()  # listen during playback → barge-in
                await self._speak(reply)
        except Exception as e:  # noqa: BLE001 — a turn fault must not kill the session
            logger.warning("discord voice: turn failed, continuing: %s", e)
        finally:
            self.receiver.resume()


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
            import discord  # optional dep

            # Plain VoiceClient — NOT voice_recv.VoiceRecvClient. The Hermes
            # receiver attaches to the raw UDP socket itself and does its own
            # RTP parse / decrypt / DAVE / Opus decode, bypassing voice_recv's
            # broken path (the "loud static" corruption). See _hermes_voice_recv.
            self._vc = await voice_channel.connect(cls=discord.VoiceClient)
        except Exception as e:  # noqa: BLE001
            logger.warning("discord voice: connect failed: %s", e)
            return f"Couldn't join voice: {e}"

        loop = asyncio.get_running_loop()

        from ._hermes_voice_recv import HermesVoiceReceiver

        def _on_voice_activity(_ssrc: int) -> None:
            # Barge-in: the instant a user speaks while Athena is talking, stop
            # her playback so they can interrupt naturally. Fires on the
            # receiver's socket thread (per packet) → hop to the loop to call
            # VoiceClient.stop (not thread-safe). NB: best with headphones; on
            # open speakers Athena's own echo can self-barge.
            vc = self._vc
            if vc is not None and vc.is_playing():
                loop.call_soon_threadsafe(vc.stop)

        receiver = HermesVoiceReceiver(
            voice_client=self._vc,
            silence_threshold_s=0.5,  # end an utterance after 0.5s of silence
            min_speech_duration_s=0.4,  # drop sub-400ms blips
            on_voice_activity=_on_voice_activity,
        )

        async def _play(wav: Path) -> None:
            await play_wav_in_vc(self._vc, wav, loop=loop)

        # Fresh, dedicated session per join so voice never drags the text
        # channel's accumulated history (which made every reply pay a
        # multi-second context compression). Approvals still route to the
        # real text channel via event.chat_id.
        import uuid

        voice_session_id = f"voice-{uuid.uuid4().hex[:12]}"

        require_consent = True
        self._session = HermesVoiceSession(
            receiver=receiver,
            transcribe=make_transcribe(stt),
            run_turn=make_voice_run_turn(self._adapter.daemon, session_id=voice_session_id),
            speak=make_speak(_play, tts),
            platform=self._adapter.name,
            chat_id=str(text_chat_id),
            require_consent=require_consent,
        )

        notice = (
            "🎙️ Athena is in the voice channel and **will transcribe what's said**. "
            "Run `/voice consent` to begin, or `/voice leave` to end."
            if require_consent
            else "🎙️ Athena is now listening. `/voice leave` to end."
        )
        await self._adapter.send_text(str(text_chat_id), notice)
        if not require_consent:
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
