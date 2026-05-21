# `video_analyze` — container + stream + per-frame analysis

One tool, seven modes, **two-layer discipline**.

## Modes

| Mode                | What it does                                           | Needs ffmpeg | Needs ffprobe |
|---------------------|--------------------------------------------------------|:------------:|:-------------:|
| `probe`             | codec / format / dimensions / fps / bitrate            | —            | yes           |
| `atoms`             | MP4/MOV box ordering + faststart remux signature       | —            | —             |
| `gop`               | I/P/B frame-type pattern + keyframe intervals          | —            | yes           |
| `encoder_fingerprint` | x264/x265 tag detection + hedged interpretation      | —            | yes           |
| `inspect`           | THE TWO-LAYER REPORT (container + stream, separately)  | —            | yes           |
| `frames`            | Extract keyframes / sampled / range PNG frames         | yes          | —             |
| `analyze`           | Frames + per-frame describe via `vision_analyze`       | yes          | —             |

The **atoms** mode is pure Python — runs without ffmpeg. That
keeps the single most useful container-tampering signal
(moov-vs-mdat ordering) available even on a stripped host.

## The two-layer discipline

The `inspect` mode returns two distinct objects:

```json
{
  "container_layer": {
    "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
    "atom_order": ["ftyp", "free", "mdat", "moov"],
    "moov_before_mdat": false,
    "remux_interpretation": "mdat precedes moov — typical of original camera capture...",
    "format_encoder_tag": "Lavf60.16.100"
  },
  "elementary_stream_layer": {
    "codec_name": "h264",
    "profile": "Constrained Baseline",
    "pix_fmt": "yuv420p",
    "width": 320, "height": 240,
    "frame_rate": "24/1",
    "stream_encoder_tags": ["x264 - core 164 ..."],
    "software_encoder_likely": true,
    "encoder_interpretation": "x264/x265 encoder tag present — produced or re-encoded by software...",
    "gop": { "frame_types_sample": "IPPPPPPP...", "i_frame_count": 3, ... }
  },
  "note": "Container observations and elementary-stream observations are reported SEPARATELY on purpose..."
}
```

**These two objects can disagree, and that's load-bearing.** A
remux pass (`ffmpeg -movflags +faststart`) reorders the container's
atoms and may add format-level encoder tags WITHOUT touching the
elementary stream. A clip that's been faststart-remuxed will show
`moov_before_mdat: true` in the container layer while its
elementary stream may still be the original hardware-encoded
bytes from the camera.

Collapsing the two layers into a single "is this video real"
boolean is exactly the failure mode this tool exists to prevent.
The output's `note` field travels with every `inspect` call,
reinforcing the discipline for the model reading the result.

## Signals vs. verdicts

Every interpretation string is **hedged**:

| Signal                                  | Interpretation                                                    |
|-----------------------------------------|-------------------------------------------------------------------|
| `moov_before_mdat == true`              | "consistent with a qt-faststart (web-optimised) remux pass"       |
| `moov_before_mdat == false`             | "typical of original camera capture and recorder output"          |
| `software_encoder_likely == true`       | "produced or re-encoded by a software encoder"                    |
| `software_encoder_likely == false`      | "consistent with hardware encode, BUT absence is NOT proof"        |

The tool surfaces signals. The analyst (or the model reasoning
over the report) weighs them. Never auto-conclude.

## Frame extraction

| Mode        | Strategy                                  | Args                             |
|-------------|-------------------------------------------|----------------------------------|
| `keyframes` | I-frames only (default)                   | —                                |
| `sampled`   | One frame every `interval_s` seconds      | `interval_s=5` (default)         |
| `range`     | Every frame between `start` and `end`     | `start`, `end` (HH:MM:SS or sec) |

The cap is `cfg.video_max_frames` (default 200) — past that,
long videos in any mode get truncated rather than exploding disk.

Frames land in `<profile_dir>/video/frames/<source-sha256-prefix>/`
named `kf_00001.png` / `s_00001.png` / `r_00001.png`. Reproducible
across reruns: the same source video produces the same directory.

## The `analyze` mode (the multiplier)

`analyze` extracts frames and routes each one through T4-01's
`vision_analyze` describe mode. The default prompt asks the
model to describe what's happening in each frame; pass your own
via the `prompt` arg.

```json
{
  "mode": "analyze",
  "frame_count": 5,
  "frames_out_dir": "/path/to/frames",
  "analyses": [
    {"frame": "kf_00001.png", "answer": "A landscape with trees..."},
    ...
  ]
}
```

When vision isn't available (`cfg.vision_enabled=False`) the
mode still extracts the frames and returns the path list, with
a clear error string about the missing provider.

## Hash-log (provenance trail)

Every call writes a JSONL row to
`<profile_dir>/video_audit.jsonl` (same shape as T4-01.2's
vision hash-log; reuses the same `HashLogger`):

```json
{"ts":"2026-05-20T13:42:00.123456Z","mode":"inspect",
 "path":"/abs/path","sha256":"abcd…","bytes":54321,
 "extra":{"moov_before_mdat":false}}
```

The bytes themselves are not stored — same calculus as the
vision log. A SHA-256 fingerprint is enough provenance without
unbounded log growth.

## Configuration

```toml
# ~/.athena/config.toml — defaults shown
video_enabled = true                    # off → tool refuses all modes
video_ffmpeg_path = "ffmpeg"            # for extraction
video_ffprobe_path = "ffprobe"          # for probe / gop / fingerprint / inspect
video_frames_dir = ""                   # "" → <profile>/video/frames
video_max_frames = 200                  # cap on extracted frames
video_default_extract = "keyframes"     # keyframes | sampled | range
video_sampled_interval_s = 5.0          # default sample interval
```

## Dependencies

External binaries:
- `ffmpeg` — required for `frames` and `analyze`. Install via
  `brew install ffmpeg` / `apt install ffmpeg` / `scoop install
  ffmpeg`.
- `ffprobe` — required for `probe`, `gop`, `encoder_fingerprint`,
  and `inspect`. Bundled with ffmpeg.

The `atoms` mode is pure Python and runs without either binary.

## Graceful degradation

| Host has...        | What works                                                              |
|--------------------|-------------------------------------------------------------------------|
| ffmpeg + ffprobe   | every mode                                                              |
| ffprobe only       | `probe`, `gop`, `encoder_fingerprint`, `inspect`, `atoms`                |
| ffmpeg only        | `frames`, `analyze`, `atoms`. The ffprobe-backed modes return a clear error |
| neither            | `atoms` only                                                            |

## Non-goals

- ~~**Audio inspection.** Out of scope for T4-02.~~ **Closed
  by T4-04** — `video_analyze mode=analyze` now extracts the
  audio track via ffmpeg and runs `audio_analyze.transcribe_track`
  on it; the transcript lands in the result under the
  `transcript` field. See `docs/reference/audio-analyze.md`.
- **DRM-protected streams.** Out of scope; this is a forensic
  tool for unprotected inputs.
- **Live streams.** The tool assumes a complete, on-disk file.
- **Verdicts.** The tool returns signals; the analyst weighs
  them.

## Reference

- Atom parser + faststart detection: `athena/video/atoms.py`
- ffprobe inspection: `athena/video/probe.py`
- Frame extraction: `athena/video/extract.py`
- Tool dispatch + mode handlers: `athena/video/analyze.py`
