# `audio_analyze` — transcription + diarization

One tool, four modes. Backend resolved via the capability
manifest, **local-preferred by default** — recordings stay
on the machine.

## Modes

| Mode         | What it does                                                    |
|--------------|-----------------------------------------------------------------|
| `transcribe` | Text + segment timestamps. The default.                        |
| `diarize`    | Transcribe + speaker labels per segment. **Opt-in via `cfg.audio_diarization_enabled`**; the default backend (faster-whisper) doesn't ship a diarizer, so segments come back with `speaker=null` until a diarizer backend lands. |
| `classify`   | Coarse content type (speech / music / silence / mixed / unknown). |
| `full`       | All of the above.                                               |

## Hash-log + transcript artifact

Every call writes:

- `<profile_dir>/audio_audit.jsonl` — one JSONL row per call:
  `{ts, mode, path, sha256, bytes, extra: {segment_count, language, duration, transcript_path, diarize}}`. Same provenance shape as T4-01 vision and T4-02 video.
- `<profile_dir>/audio/<source-stem>_<sha8>.json` — full result, machine-readable.
- `<profile_dir>/audio/<source-stem>_<sha8>.txt` — one line per segment with timestamps + optional speaker prefix; grep-friendly operator view.

The sha-prefix in the filename means reruns on the same source overwrite predictably — no log growth, easy to find.

## Backend resolution

`MediaRegistry.backend_for("audio_transcription")` finds the first registered provider whose capability manifest declares `audio_transcription=True`. With `cfg.media_backend_prefer = "local"` (default), any backend with `is_local=True` wins.

In-tree backend: `athena/audio/backends/faster_whisper_local.py` — Whisper-class STT via [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Model files cache under `~/.cache/huggingface/`; first use downloads, subsequent calls reuse. Configurable via:

```toml
audio_whisper_model = "base"     # tiny | base | small | medium | large-v3
audio_whisper_device = "auto"    # auto | cpu | cuda
audio_whisper_compute_type = "auto"  # auto | int8 | float16 | float32
```

No backend declares the capability → the tool returns `{"available": false, "reason": "no audio backend configured"}` — **not** an error.

## Long-audio chunking

Files longer than `cfg.audio_chunk_seconds` (default 30 s) are chunked with `cfg.audio_chunk_overlap_s` (default 2 s) of overlap. The tool:

1. Computes window boundaries via `_chunk_boundaries(duration, chunk_s, overlap_s)` — successive windows step by `chunk_s - overlap_s`.
2. Calls the backend once per window with `chunk_offset_s` set, so segment timestamps come back in **absolute** file-seconds (not chunk-relative).
3. Stitches via `_stitch(...)` which dedupes segments at chunk seams: a segment in the overlap region of chunk N+1 that matches text + rounded-start of a segment from chunk N is dropped.

The seam-integrity invariant: **words spoken at chunk boundaries appear once in the output, not twice.** Pinned by `test_stitch_dedupes_seam_repeat`. And the converse: genuine repeat phrases later in the audio are NOT dropped (pinned by `test_stitch_keeps_segments_outside_overlap_even_if_text_repeats`).

`progress(done, total)` callback fires per chunk for CLI surfaces. `progress(1, 1)` also fires for the single-shot (short-audio) path so a UI can confirm completion uniformly.

## Diarization is opt-in

Two gates must both be open before the backend gets `diarize=True`:

1. `cfg.audio_diarization_enabled` — the operator-level decision (default **False** because diarization is heavier; many callers only need the transcript).
2. `mode` in `{"diarize", "full"}` — the per-call decision.

Backends that don't support diarization return segments with `speaker=None` per the `AudioBackend` Protocol contract; the tool's `to_dict` omits the `speaker` field when it's None so the JSON output stays clean.

A future `pyannote_diarizer` backend can declare a separate capability and compose with the transcription backend.

## Video integration (closes the T4-02 audio gap)

`athena.audio.tools.transcribe_track(path, *, cfg, backend?)` is the composable helper that bypasses the tool layer's JSON formatting and returns a raw `TranscribeResult`.

T4-02's `video_analyze mode=analyze` calls `_default_audio_transcribe_fn(cfg)`, which:

1. Demuxes the video's audio track to a temp 16 kHz mono WAV via `ffmpeg -vn -ac 1 -ar 16000 -acodec pcm_s16le`.
2. Calls `transcribe_track(<wav>, cfg=cfg)`.
3. Cleans up the temp WAV (the persistent artifact is the transcript JSON under `<profile>/audio/`).

The transcript lands in `video_analyze`'s result under a `transcript` field:

```json
{
  "mode": "analyze",
  "frame_count": 12,
  "analyses": [{"frame": "...", "answer": "..."}, ...],
  "transcript": {
    "segments": [{"start": 0.0, "end": 2.5, "text": "..."}, ...],
    "language": "en",
    "duration": 47.2
  }
}
```

Defensive: audio extraction failure / no audio stream / backend exception → the analyze result still returns cleanly, just without the transcript field. **Audio failure must not break video analysis.** Pinned by `test_analyze_mode_handles_audio_fn_exception`.

## Tool result shape

```json
{
  "available": true,
  "mode": "transcribe",
  "path": "/abs/path/audio.wav",
  "sha256": "abcd…",
  "transcript_path": "/abs/path/profile/audio/audio_abcd1234.json",
  "segments": [
    {"start": 0.0,  "end": 3.45, "text": "hello world"},
    {"start": 3.45, "end": 5.10, "text": "how are you", "speaker": "SPK0"}
  ],
  "language": "en",
  "duration": 5.1,
  "content_type": "speech"
}
```

Errors are structured JSON:

```json
{"available": false, "error": "file not found: /no/such.wav", "mode": "transcribe"}
{"available": false, "reason": "no audio backend configured",  "mode": "transcribe"}
{"available": true,  "error": "transcribe failed: RuntimeError: model offline", "mode": "transcribe", "path": "...", "sha256": "..."}
```

The tool never raises into the model loop.

## Configuration

```toml
audio_analyze_enabled = true
audio_backend_prefer = "local"
audio_diarization_enabled = false       # opt-in operator gate
audio_chunk_seconds = 30.0
audio_chunk_overlap_s = 2.0
audio_whisper_model = "base"            # ~74 MB; first use downloads
audio_whisper_device = "auto"
audio_whisper_compute_type = "auto"
audio_output_dir = ""                   # "" → <profile>/audio/
```

## Dependencies

The default backend needs `faster-whisper` installed:

```bash
pip install faster-whisper
```

Without it, the broker finds no `audio_transcription`-capable provider and the tool surfaces "no backend configured" cleanly. The rest of athena works fine.

## Non-goals

- **Real-time / streaming transcription.** The tool assumes a complete on-disk file.
- **Audio generation / TTS.** Different capability surface entirely; would land as a separate phase.
- **Speaker diarization in the default backend.** faster-whisper proper doesn't ship one. Diarization mode honors the contract (returns `speaker=None`) and waits for a future diarizer backend.
- **Audio classification beyond speech/music/silence.** Coarse only.

## Reference

- Contract: `athena/audio/job.py`
- Backend: `athena/audio/backends/faster_whisper_local.py`
- Tool + chunking: `athena/audio/tools.py`
- Video integration: `athena/video/analyze.py:_default_audio_transcribe_fn` + `_extract_audio_track`
- Vision sibling: `docs/reference/vision-analyze.md`
- Video sibling: `docs/reference/video-analyze.md`
