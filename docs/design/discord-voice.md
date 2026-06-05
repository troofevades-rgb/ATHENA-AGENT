# Design: Discord voice chat (Tier 1)

**Status:** Proposed / not yet built.
**Scope:** Let Athena join a Discord voice channel, listen to a spoken
utterance, run a normal agent turn, and speak the reply back.

The guiding principle: **voice is an I/O skin, not a new agent.** The
hard parts of the gateway — session routing, the per-conversation agent
pool, the busy-turn guard, approval routing, continuity — already exist
and are platform-neutral. Voice should produce the same
`MessageEvent` the text path produces and consume the same reply text,
so it inherits all of that for free. The genuinely new code is audio
capture, segmentation, STT plumbing (the model already exists), TTS
(new), and playback.

## Goals (Tier 1)

- `/athena voice join` — bot joins the caller's voice channel.
- Half-duplex, single-utterance turns: a user speaks → Athena
  transcribes → runs one agent turn → speaks the answer.
- Command-initiated and bounded (idle auto-disconnect, max session).
- Graceful degradation: if voice deps or a backend are missing, voice
  commands report "unavailable" and the **text path is unaffected**.
- Consent-first: recording is announced and opt-in.

## Non-goals (deferred to Tier 2)

- Always-on continuous listening, natural barge-in, simultaneous
  multi-speaker transcription, streaming (sub-utterance) STT/TTS,
  voice-based approval yes/no. These are real projects; v1 must not
  pretend to do them.

## Data flow

```
                    Discord voice channel
                            │ Opus frames (per speaker)
                            ▼
  ┌───────────────── DiscordVoiceSession (per channel) ──────────────────┐
  │  VoiceReceiver ──► VAD segmenter ──► utterance WAV (temp)            │
  │       (sink)         (webrtcvad)        │                            │
  │                                         ▼                            │
  │                              AudioBackend.transcribe()  [EXISTS]     │
  │                                         │ text                       │
  └─────────────────────────────────────────┼──────────────────────────┘
                                            ▼
                        MessageEvent(platform="discord",
                          chat_id=<voice-channel-id>, user_id=<speaker>,
                          text=<transcript>, message_type=VOICE,
                          attachments=[utterance.wav])
                                            │
                              daemon.handle_inbound(event)   [EXISTS]
                          (router → agent pool → turn → busy guard,
                           approvals, continuity — all reused)
                                            │ reply text
                                            ▼
                        VoiceReplySink (adapter-registered)
                                            │
                              SpeechSynthBackend.synthesize()  [NEW]
                                            │ PCM/wav
                                            ▼
                          voice_client.play(FFmpegPCMAudio(...))  → channel
```

Everything between `MessageEvent` and "reply text" is **unchanged
existing code**. Voice only adds the two ends.

## Module layout

```
athena/audio/tts/                      NEW — text-to-speech, mirrors STT
  base.py            SpeechSynthBackend Protocol + SynthResult
  resolve.py         resolve_tts_backend(cfg) selector (mirrors videogen)
  backends/
    piper_local.py   local Piper (no key, ONNX voices) — default
    stub.py          deterministic silent/marker wav — tests + headless
athena/gateway/voice/                  NEW — platform-neutral voice glue
  session.py         VoiceSession state machine (join→listen→speak→idle)
  segmenter.py       VAD-based utterance segmentation (webrtcvad)
  receiver.py        VoiceReceiver ABC (capture seam, impl is platform)
athena/gateway/platforms/discord_voice.py   NEW — discord-specific receiver
                     wraps discord-ext-voice-recv sink + FFmpeg playback
```

`DiscordAdapter` gains `voice_join(channel)` / `voice_leave()` and owns
the active `DiscordVoiceSession`. Nothing in `daemon.py`, `router.py`,
`agent_pool.py`, or `approval_routing.py` changes.

## Backend abstractions

STT already follows a clean Protocol (`athena/audio/job.py:AudioBackend`
— `is_available()`, `transcribe(path) -> TranscribeResult`,
`classify()`), with a local faster-whisper backend. TTS mirrors it:

```python
class SpeechSynthBackend(Protocol):
    name: str
    def is_available(self) -> bool: ...
    def synthesize(self, text: str, *, voice: str | None = None,
                   sample_rate: int = 48_000) -> SynthResult: ...
```

`SynthResult` carries the output path (or PCM bytes), sample rate, and
duration. `resolve_tts_backend(cfg)` honors `cfg...voice.tts_backend`
first, then a capability broker (same shape as `videogen.resolve_backend`).
Default `piper_local` (offline, on-brand with the air-gapped posture);
`stub` for tests and for hosts without a TTS lib.

**Why the receiver is an ABC.** Mainline `discord.py` 2.x has no voice
*receive*. The capture seam (`VoiceReceiver`) is platform-neutral so the
discord-specific implementation (via `discord-ext-voice-recv`, or pycord
sinks if we ever switch) is isolated to one file. If the ecosystem
shifts, only `discord_voice.py` changes — the session, segmenter, STT,
TTS, and the whole agent path don't.

## VoiceSession state machine

```
IDLE ──join──► CONNECTING ──ready──► LISTENING
LISTENING ──utterance complete──► TRANSCRIBING ──text──► THINKING
THINKING ──reply text──► SPEAKING ──playback done──► LISTENING
any ──/stop or error──► LISTENING (interrupt) ; ──leave/idle/maxlife──► IDLE
```

Half-duplex is enforced by the state: capture is **paused while
SPEAKING** (no self-transcription of Athena's own voice). `/stop` (an
existing bypass command) interrupts playback and the in-flight turn and
returns to LISTENING — that is the v1 barge-in.

## Concurrency & back-pressure

- The Discord client runs on the asyncio loop. Opus decode + VAD are
  cheap and stay on the loop.
- STT (faster-whisper) and TTS (Piper) are **blocking/CPU-heavy** → run
  via `asyncio.to_thread` so they never stall the voice/event loop.
- The agent turn runs through the existing `AgentPool` (sync agent on a
  worker), reached via `daemon.handle_inbound` — already the model for
  the text path.
- **Back-pressure:** one in-flight utterance per channel. While
  TRANSCRIBING/THINKING/SPEAKING, further utterances are dropped with a
  brief spoken/typed "one moment" rather than queued unbounded. (Tier 2
  can add a bounded queue + interruption.) This mirrors the existing
  busy-session guard in `base.py` — voice piggybacks on it.

## Approvals while in voice

A tool that needs confirmation mid-turn must not try to parse a spoken
"yes". v1 routes the approval to the **text channel** using the
adapter's *existing* `discord.ui.View` button renderer (already wired
through `daemon.approvals.register_platform_renderer`), and Athena
**speaks a pointer**: "I need your approval — check the channel." The
button resolves the approval exactly as it does for text today. Robust,
zero new approval surface. (Tier 2 could add a constrained spoken
yes/no with explicit re-confirmation.)

## Consent & privacy (load-bearing, not optional)

Recording people's voices has legal and ToS weight. v1:

- On join, post a visible notice in the linked text channel
  ("🎙️ Athena is now listening in <channel> — say `/athena voice leave`
  or anyone can `/stop` to end it.") and only start capture after.
- `require_consent = true` (default): the bot will not capture until a
  configured opt-in (a reaction/button) is given by the channel.
- Never persist raw audio beyond the single utterance temp file; delete
  it immediately after transcription (the existing tool-result / blob
  retention does **not** apply to raw voice). Transcripts follow the
  normal session-redaction rules.
- All voice tool calls run under their own provenance origin
  (`subagent`-style) so the audit log distinguishes voice-initiated
  actions.

## Config schema

```toml
[gateway.platforms.discord.voice]
enabled = false                 # opt-in; off by default
require_consent = true
stt_backend = "faster_whisper_local"   # reuses the existing audio backend
tts_backend = "piper_local"
tts_voice = ""                  # backend-specific voice id; "" = default
vad_aggressiveness = 2          # webrtcvad 0–3
min_utterance_ms = 400          # ignore blips
max_utterance_ms = 30000        # hard cap per turn
silence_hangover_ms = 800       # trailing silence that ends an utterance
idle_disconnect_s = 300         # auto-leave after silence
max_session_s = 3600            # hard lifetime cap
barge_in = true                 # /stop interrupts playback
```

All default-safe; `enabled = false` means the feature is inert and the
deps need not be installed.

## Dependency gating

New optional extra so headless / text-only installs stay slim:

```toml
[project.optional-dependencies]
gateway-voice = [
  "discord.py[voice]>=2.4",     # PyNaCl for the voice UDP transport
  "discord-ext-voice-recv",     # the receive sink discord.py lacks
  "webrtcvad",                  # utterance segmentation
  "piper-tts",                  # local TTS (default backend)
]
```

faster-whisper already ships under the audio extra; FFmpeg is already a
documented runtime dep (video frame extraction). `is_available()` on
each backend + a startup probe means a missing piece degrades to
"voice unavailable", never a crash.

## Failure isolation

Every stage is wrapped so a fault can't escape the voice session:

- A bad frame / decode error → dropped, logged at debug, capture
  continues.
- STT or TTS exception → the turn fails soft: Athena says "sorry, I
  didn't catch that" (or posts to text) and returns to LISTENING; the
  daemon and text adapter are untouched.
- VoiceSession crash → caught at the adapter boundary (same pattern as
  the daemon's per-adapter task `_on_done` guard); the bot leaves the
  VC cleanly and the text path keeps running.
- Resource caps (`max_utterance_ms`, `idle_disconnect_s`,
  `max_session_s`, single concurrent session per guild) bound runaway
  cost and stuck connections.

## Testing strategy (hermetic, matches the repo)

No real Discord, no real audio hardware — same discipline as the rest
of the gateway tests:

- **TTS backends:** `stub` round-trips; `piper_local.is_available()`
  False without the lib → resolver falls back cleanly.
- **Segmenter:** feed synthetic PCM (speech burst + silence) → assert it
  emits exactly one utterance with the right boundaries; sub-`min`
  blips ignored; over-`max` truncated.
- **Session pipeline:** a `FakeVoiceReceiver` injects a scripted PCM
  utterance and a `FakeVoiceClient` records `play()` calls. Assert: a
  `MessageEvent(message_type=VOICE, text=<stub transcript>)` is
  dispatched into a fake daemon, and the reply text drives exactly one
  `synthesize()` + one `play()`. Half-duplex: no capture while SPEAKING.
- **Approvals-in-voice:** a tool needing confirmation → assert the
  existing button renderer fires on the text channel and playback speaks
  the pointer.
- **Consent gate:** `require_consent=true` → no capture before opt-in.
- **Graceful degrade:** `enabled=false` / missing deps → `/athena voice
  join` returns "voice unavailable", text path asserted unaffected.

## Phased build order

1. **TTS backend abstraction** (`athena/audio/tts/`) + `stub` + `piper_local`
   + resolver + tests. Independently useful (also powers a future
   `speak` tool).
2. **Platform-neutral voice core** (`segmenter`, `VoiceReceiver` ABC,
   `VoiceSession` state machine) against fakes — full pipeline tested
   with zero Discord.
3. **Discord wiring** (`discord_voice.py`: voice-recv sink + FFmpeg
   playback) + `voice_join`/`voice_leave` + the `/athena voice` slash
   subcommand + consent notice.
4. **Hardening:** resource caps, idle disconnect, `/stop` barge-in,
   failure isolation, the `[gateway-voice]` extra, docs, and a
   live-dogfood runbook (manual, like the MCP/proxy runbooks).

## Open questions / risks

- **Voice-receive library choice** is the one real fork: `discord-ext-
  voice-recv` (keeps the current adapter) vs migrating to **Py-cord**
  (native sinks, but a library swap touching the whole adapter).
  Recommendation: the extension, isolated behind `VoiceReceiver`, so the
  decision is reversible and contained to one file.
- **Latency budget.** Utterance-end → spoken reply = VAD hangover +
  STT + agent turn + TTS + playback start. Local Whisper + Piper on CPU
  is usable for turn-based v1 but not for Tier-2 real-time; measure
  early and surface it in the runbook.
- **Per-speaker attribution** in a multi-person channel: v1 transcribes
  whoever crosses VAD; if two talk at once the segment is mixed. Tier 2
  needs per-SSRC sinks. Document the v1 limitation rather than hide it.
