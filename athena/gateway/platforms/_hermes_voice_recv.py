"""Minimal Discord voice receiver — bypasses discord-ext-voice-recv.

``discord-ext-voice-recv`` produced corrupted PCM ("loud static", whisper
only hallucinating) because of three bugs in its RTP path: it never decrypts
**DAVE** (Discord's E2EE voice, now default), its fixed-12-byte RTP header
parse breaks on CSRC/extension packets, and it never strips RTP padding (the
pad bytes get fed to the Opus decoder as audio).

This receiver reads the raw UDP socket directly and does the minimum that
makes audio actually work:

  1. attach to the socket (``add_socket_listener``) — pre-decrypt, pre-Opus;
  2. parse the RTP header at its real, dynamic size (CSRC + extension);
  3. NaCl ``aead_xchacha20_poly1305_rtpsize`` decrypt (header = AAD, last 4
     bytes = nonce); skip the encrypted extension; **strip RTP padding**;
  4. DAVE decrypt via ``davey`` (the SSRC→user_id needed for it comes from
     the SPEAKING op-5, with a try-decrypt fallback when op-5 doesn't fire);
  5. per-SSRC Opus decode → 48 kHz stereo PCM buffer;
  6. ``check_silence()`` (polled) returns completed utterances as
     ``(user_id, pcm_bytes_48k_stereo)``.

Nothing else — no resync watchdog, op-11/13/18 handling, probe, or health
metrics. Just the audio path.
"""

from __future__ import annotations

import array
import logging
import os
import struct
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

import discord
import discord.opus

log = logging.getLogger("athena.gateway.voice.hermes_recv")

# Barge-in gating: fire the interrupt only on SUSTAINED LOUD speech so a
# breath, click, or background hum doesn't cut Athena off. RMS floor is for
# decoded 48k s16 stereo (real speech ~2000-12000); FRAMES is consecutive
# 20ms frames above it (8 ≈ 160ms of deliberate talking).
_BARGE_RMS = 1800.0
_BARGE_FRAMES = 8


def _pcm_rms(pcm: bytes) -> float:
    s = array.array("h")
    s.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not s:
        return 0.0
    return float((sum(x * x for x in s) / len(s)) ** 0.5)


def ensure_opus_loaded() -> bool:
    """Force-load libopus from discord.py's bundled DLL.

    Plain ``discord.VoiceClient`` does NOT load libopus, and
    ``discord.opus.Decoder().decode()`` then returns all-zero PCM **without
    raising** — every utterance silently decodes to rms=0. Idempotent."""
    try:
        if discord.opus.is_loaded():
            return True
    except Exception:  # noqa: BLE001
        pass
    pkg_dir = os.path.dirname(discord.__file__)
    for path in (
        os.path.join(pkg_dir, "bin", "libopus-0.x64.dll"),
        os.path.join(pkg_dir, "bin", "libopus-0.dll"),
        "libopus-0.dll",
        "libopus.so.0",
        "libopus.dylib",
    ):
        try:
            discord.opus.load_opus(path)
            if discord.opus.is_loaded():
                log.info("loaded libopus from %s", path)
                return True
        except Exception:  # noqa: BLE001
            continue
    log.error("LIBOPUS NOT LOADED — voice decode will be silent (rms=0)")
    return False


class HermesVoiceReceiver:
    """Capture + decode Discord voice. Attach after the VC is connected,
    poll :meth:`check_silence` for completed ``(user_id, pcm_48k_stereo)``."""

    SAMPLE_RATE = 48000
    CHANNELS = 2
    _PT_VOICE = 0x78  # RTP payload type for Discord voice

    def __init__(
        self,
        voice_client: Any,
        *,
        silence_threshold_s: float = 0.7,
        min_speech_duration_s: float = 0.5,
        on_voice_activity: Callable[[int], None] | None = None,
    ) -> None:
        self._vc = voice_client
        self._silence_threshold = silence_threshold_s
        self._min_speech_duration = min_speech_duration_s
        self._on_voice_activity = on_voice_activity  # fired on sustained speech
        self._barge_streak = 0  # consecutive loud frames, for barge-in gating
        self._running = False
        self._paused = False
        # Decryption state (filled in start()).
        self._secret_key: bytes | None = None
        self._dave_session: Any = None
        self._bot_ssrc = 0
        # Per-SSRC state.
        self._lock = threading.Lock()
        self._ssrc_to_user: dict[int, int] = {}
        self._buffers: dict[int, bytearray] = defaultdict(bytearray)
        self._last_packet_time: dict[int, float] = {}
        self._decoders: dict[int, Any] = {}  # int -> discord.opus.Decoder

    # ---- lifecycle ----

    def start(self) -> None:
        conn = self._vc._connection
        if not conn.secret_key:
            raise RuntimeError("voice secret_key not ready — call start() after the handshake")
        self._secret_key = bytes(conn.secret_key)
        self._dave_session = getattr(conn, "dave_session", None)
        self._bot_ssrc = conn.ssrc
        ensure_opus_loaded()
        self._install_speaking_hook(conn)
        conn.add_socket_listener(self._on_packet)
        self._running = True
        log.info(
            "voice receiver started (bot_ssrc=%d dave=%s)", self._bot_ssrc, bool(self._dave_session)
        )

    def stop(self) -> None:
        self._running = False
        try:
            self._vc._connection.remove_socket_listener(self._on_packet)
        except Exception:  # noqa: BLE001
            pass
        with self._lock:
            self._buffers.clear()
            self._last_packet_time.clear()
            self._decoders.clear()
            self._ssrc_to_user.clear()

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    # ---- SSRC → user_id (needed for DAVE decrypt) ----

    def map_ssrc(self, ssrc: int, user_id: int) -> None:
        with self._lock:
            self._ssrc_to_user[ssrc] = user_id

    def _install_speaking_hook(self, conn: Any) -> None:
        """Capture SPEAKING (op 5) to map ssrc→user_id. Wrap the connection
        hook AND the live websocket hook so it takes effect immediately and
        survives reconnects."""
        original = conn.hook
        recv = self

        async def wrapped(ws: Any, msg: Any) -> None:
            try:
                if isinstance(msg, dict) and msg.get("op") == 5:
                    d = msg.get("d") or {}
                    ssrc, uid = d.get("ssrc"), d.get("user_id")
                    if ssrc and uid:
                        recv.map_ssrc(int(ssrc), int(uid))
            except Exception:  # noqa: BLE001
                pass
            if original:
                await original(ws, msg)

        conn.hook = wrapped
        try:
            from discord.utils import MISSING

            if getattr(conn, "ws", MISSING) is not MISSING:
                conn.ws._hook = wrapped
        except Exception:  # noqa: BLE001
            pass

    def _try_map_ssrc(self, ssrc: int, ciphertext: bytes) -> tuple[int, bytes | None]:
        """When op-5 hasn't mapped this SSRC yet, brute-force DAVE decrypt
        against each channel member — the user whose per-user MLS key
        decrypts IS the speaker (AEAD authenticates the sender, so a false
        map is impossible). Returns (user_id, plaintext) or (0, None)."""
        import davey

        try:
            bot = self._vc.user.id if self._vc.user else 0
            members = [m.id for m in self._vc.channel.members if m.id != bot]
        except Exception:  # noqa: BLE001
            return 0, None
        with self._lock:
            already = set(self._ssrc_to_user.values())
        for uid in members:
            if uid in already:
                continue
            try:
                pt = self._dave_session.decrypt(uid, davey.MediaType.audio, ciphertext)
            except Exception:  # noqa: BLE001 — wrong key → AEAD auth fails, try next
                continue
            self.map_ssrc(ssrc, uid)
            return uid, pt
        return 0, None

    # ---- packet handler (runs on the socket-reader thread) ----

    def _on_packet(self, data: bytes) -> None:
        if not self._running or self._paused or len(data) < 16:
            return
        # RTP v2 + Discord voice payload type only.
        if (data[0] >> 6) != 2 or (data[1] & 0x7F) != self._PT_VOICE:
            return
        first = data[0]
        _, _, _seq, _ts, ssrc = struct.unpack_from(">BBHII", data, 0)

        # Refresh connection state EVERY packet so a voice-WS reconnect (which
        # rotates secret_key / ssrc / the DAVE session) doesn't permanently
        # deafen us with a stale key. Cheap attribute reads + a 32-byte copy.
        conn = self._vc._connection
        secret = getattr(conn, "secret_key", None)
        if not secret:
            return  # mid-(re)connect — no key yet
        self._secret_key = bytes(secret)
        self._bot_ssrc = conn.ssrc
        self._dave_session = getattr(conn, "dave_session", None)
        if ssrc == self._bot_ssrc:
            return  # never capture our own audio

        # Dynamic RTP header size (CSRC count + extension bit).
        cc = first & 0x0F
        has_ext = bool(first & 0x10)
        has_pad = bool(first & 0x20)
        header_size = 12 + 4 * cc + (4 if has_ext else 0)
        if len(data) < header_size + 4:
            return
        ext_len = 0
        if has_ext:
            ext_words = struct.unpack_from(">H", data, 12 + 4 * cc + 2)[0]
            ext_len = ext_words * 4

        header = bytes(data[:header_size])
        payload = data[header_size:]
        if len(payload) < 4:
            return

        # NaCl aead_xchacha20_poly1305_rtpsize: nonce = last 4 bytes, AAD = header.
        nonce = bytearray(24)
        nonce[:4] = payload[-4:]
        try:
            import nacl.secret

            dec = nacl.secret.Aead(self._secret_key).decrypt(
                bytes(payload[:-4]), header, bytes(nonce)
            )
        except Exception:  # noqa: BLE001
            return

        if ext_len and len(dec) > ext_len:
            dec = dec[ext_len:]  # skip encrypted extension
        if has_pad:  # RTP padding: last byte = pad length (incl. itself) — strip it
            if not dec:
                return
            pad = dec[-1]
            if pad == 0 or pad > len(dec):
                return
            dec = dec[:-pad]
            if not dec:
                return

        # DAVE E2EE decrypt (needs the speaker's user_id).
        if self._dave_session:
            with self._lock:
                uid = self._ssrc_to_user.get(ssrc, 0)
            if uid:
                import davey

                try:
                    dec = self._dave_session.decrypt(uid, davey.MediaType.audio, dec)
                except Exception as e:  # noqa: BLE001
                    if "Unencrypted" not in str(e):
                        return  # genuinely encrypted but we failed — drop
            else:
                uid, plaintext = self._try_map_ssrc(ssrc, dec)
                if not uid or plaintext is None:
                    return
                dec = plaintext

        # Opus decode → 48 kHz stereo PCM.
        try:
            if ssrc not in self._decoders:
                self._decoders[ssrc] = discord.opus.Decoder()  # type: ignore[no-untyped-call,unused-ignore]
            pcm = self._decoders[ssrc].decode(dec)
            with self._lock:
                self._buffers[ssrc].extend(pcm)
                self._last_packet_time[ssrc] = time.monotonic()
        except Exception:  # noqa: BLE001
            return

        # Barge-in: only after a sustained run of LOUD frames (not a blip /
        # breath / background hum). The controller's hook stops playback when
        # Athena is mid-reply.
        if self._on_voice_activity is not None:
            if _pcm_rms(pcm) >= _BARGE_RMS:
                self._barge_streak += 1
                if self._barge_streak >= _BARGE_FRAMES:
                    self._barge_streak = 0
                    try:
                        self._on_voice_activity(ssrc)
                    except Exception:  # noqa: BLE001
                        pass
            else:
                self._barge_streak = 0

    # ---- utterance polling ----

    def check_silence(self) -> list[tuple[int, bytes]]:
        """Return ``[(user_id, pcm_48k_stereo), ...]`` for speakers who've gone
        quiet for ``silence_threshold_s`` with at least ``min_speech_duration_s``
        of buffered audio. Call periodically from the event loop."""
        now = time.monotonic()
        out: list[tuple[int, bytes]] = []
        with self._lock:
            for ssrc in list(self._buffers.keys()):
                quiet = now - self._last_packet_time.get(ssrc, now)
                buf = self._buffers[ssrc]
                dur = len(buf) / (self.SAMPLE_RATE * self.CHANNELS * 2)
                if quiet >= self._silence_threshold and dur >= self._min_speech_duration:
                    uid = self._ssrc_to_user.get(ssrc, 0)
                    if uid:
                        out.append((uid, bytes(buf)))
                    self._buffers[ssrc] = bytearray()
                    self._last_packet_time.pop(ssrc, None)
                elif quiet >= self._silence_threshold * 2:
                    self._buffers.pop(ssrc, None)  # stale / unmapped — discard
                    self._last_packet_time.pop(ssrc, None)
        return out
