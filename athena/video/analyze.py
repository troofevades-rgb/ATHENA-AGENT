"""video_analyze — the model-facing entry point (T4-02.5).

One tool, seven modes:

  probe                  ffprobe codec / format / stream summary
  atoms                  pure-Python MP4/MOV box parser +
                         faststart remux signature
  gop                    I/P/B frame-type pattern + keyframe
                         intervals
  encoder_fingerprint    x264/x265 tag detection + hedged
                         interpretation
  inspect                THE TWO-LAYER REPORT — container layer
                         + elementary-stream layer reported
                         SEPARATELY (the load-bearing discipline)
  frames                 extract keyframes / sampled / range
                         PNG frames; returns the path list
  analyze                extract + route each frame through
                         T4-01's vision_analyze describe mode

Every read sha256s the source video and writes a JSONL row to
<profile_dir>/video_audit.jsonl (provenance trail — same
pattern as T4-01.2's vision hash-log).

Sync throughout (athena's runtime; the spec was async).

The TWO-LAYER discipline: container observations (atom
ordering, format-level encoder tag, faststart signature) and
elementary-stream observations (codec, profile, GOP, stream-
level encoder tag) are NEVER collapsed into a single "is it
real" boolean. A remux pass can touch the container while the
underlying stream is authentic; that distinction is the whole
point of this tool. Pinned by test_inspect_keeps_layers_separate.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from ..config import load_config, profile_dir
from ..vision.hashlog import HashLogger, sha256_file
from . import atoms as atoms_mod
from . import extract as extract_mod
from . import probe as probe_mod

logger = logging.getLogger(__name__)


VALID_MODES = (
    "probe", "atoms", "gop", "encoder_fingerprint",
    "inspect", "frames", "analyze",
)
VALID_EXTRACT = ("keyframes", "sampled", "range")


_VIDEO_AUDIT_FILENAME = "video_audit.jsonl"


def video_audit_path(profile_dir_path: Path | str) -> Path:
    return Path(profile_dir_path) / _VIDEO_AUDIT_FILENAME


# ProviderFn: a callable that accepts a frame path + a prompt
# and returns the model's answer string. Tests inject a stub;
# production wires through T4-01's vision_analyze describe mode.
ProviderFn = Callable[[Path, str], str]

# AudioTranscribeFn: closes the gap T4-02 originally punted on.
# T4-04 wires this — given a video path, return a dict matching
# the TranscribeResult shape (segments + language + duration)
# OR None when audio analysis can't run on this host. Tests
# inject a stub; production routes via athena.audio.tools.transcribe_track.
AudioTranscribeFn = Callable[[Path], dict[str, Any] | None]


def _default_provider_fn(cfg: Any) -> ProviderFn | None:
    """Build a ProviderFn that routes each frame through
    vision_analyze in describe mode. Returns None when vision
    isn't usable on this host (vision_enabled=False)."""
    if not getattr(cfg, "vision_enabled", True):
        return None
    from ..vision.analyze import _run as vision_run

    def _fn(frame_path: Path, prompt: str) -> str:
        out = vision_run(
            mode="describe",
            path=str(frame_path),
            prompt=prompt,
            _cfg=cfg,
        )
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return ""
        return str(data.get("answer", ""))

    return _fn


def _default_audio_transcribe_fn(cfg: Any) -> AudioTranscribeFn | None:
    """Build an AudioTranscribeFn that extracts the audio
    stream from the source video into a temp WAV, runs
    athena.audio.tools.transcribe_track on it, returns the
    TranscribeResult as a dict. Closes the T4-02 audio gap.

    Returns None when cfg.audio_analyze_enabled is False or
    ffmpeg isn't on PATH (we use ffmpeg to demux the audio
    track; without it audio analysis can't run on a video
    input).
    """
    if not getattr(cfg, "audio_analyze_enabled", True):
        return None
    import shutil as _shutil
    va = getattr(cfg, "video_analysis", None)
    ffmpeg_path = va.ffmpeg_path if va is not None else "ffmpeg"
    if not _shutil.which(ffmpeg_path):
        return None

    def _fn(video_path: Path) -> dict[str, Any] | None:
        wav_path = _extract_audio_track(video_path, cfg=cfg)
        if wav_path is None:
            return None
        try:
            from ..audio.tools import transcribe_track
            result = transcribe_track(wav_path, cfg=cfg)
            return result.to_dict()
        except Exception as e:  # noqa: BLE001
            logger.warning("video.audio transcribe failed: %s", e)
            return None
        finally:
            try:
                wav_path.unlink()
            except OSError:
                pass

    return _fn


def _extract_audio_track(
    video_path: Path,
    *,
    cfg: Any,
    timeout_s: float = 60.0,
) -> Path | None:
    """Demux the video's audio stream to a mono 16 kHz WAV in
    a temp location. Returns the WAV path on success, None on
    failure (no audio stream, ffmpeg error, etc.). Mono +
    16 kHz matches what whisper-class models want; smaller
    files = faster transcription."""
    import subprocess
    import tempfile

    va = getattr(cfg, "video_analysis", None)
    ffmpeg = va.ffmpeg_path if va is not None else "ffmpeg"
    tmp = (
        Path(tempfile.gettempdir())
        / f"athena_audio_{video_path.stem}_{video_path.stat().st_size}.wav"
    )
    try:
        proc = subprocess.run(
            [
                ffmpeg, "-y",
                "-i", str(video_path),
                "-vn",                  # no video
                "-ac", "1",             # mono
                "-ar", "16000",         # 16 kHz
                "-acodec", "pcm_s16le",
                str(tmp),
            ],
            capture_output=True, timeout=timeout_s, check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg audio demux timed out for %s", video_path)
        return None

    if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        logger.info(
            "ffmpeg audio demux skipped (no audio stream or error) for %s",
            video_path,
        )
        return None
    return tmp


def _resolve_paths(cfg: Any) -> dict[str, Path]:
    pdir = profile_dir(getattr(cfg, "profile", "default"))
    va = getattr(cfg, "video_analysis", None)
    frames_root = (
        Path(va.frames_dir)
        if va is not None and va.frames_dir
        else pdir / "video" / "frames"
    )
    return {
        "profile": pdir,
        "audit": video_audit_path(pdir),
        "frames_root": frames_root,
    }


# ---------------------------------------------------------------
# Mode handlers
# ---------------------------------------------------------------


def _handle_probe(path: Path, cfg: Any, log: HashLogger) -> dict[str, Any]:
    sha = sha256_file(path)
    try:
        probe = probe_mod.ffprobe_json(
            path, ffprobe=cfg.video_analysis.ffprobe_path,
        )
    except probe_mod.FFprobeMissing as e:
        return {"mode": "probe", "path": str(path), "sha256": sha,
                "error": str(e)}
    log.log(mode="probe", path=path, sha256=sha,
            size_bytes=path.stat().st_size)
    return {
        "mode": "probe",
        "path": str(path),
        "sha256": sha,
        "summary": probe_mod.codec_summary(probe),
    }


def _handle_atoms(path: Path, log: HashLogger) -> dict[str, Any]:
    sha = sha256_file(path)
    a = atoms_mod.parse_top_level_atoms(path)
    sig = atoms_mod.faststart_remux_signature(a)
    log.log(
        mode="atoms", path=path, sha256=sha,
        size_bytes=path.stat().st_size,
        extra={"atom_order": sig["atom_order"]},
    )
    return {"mode": "atoms", "path": str(path), "sha256": sha,
            **sig}


def _handle_gop(path: Path, cfg: Any, log: HashLogger) -> dict[str, Any]:
    sha = sha256_file(path)
    try:
        gop = probe_mod.gop_structure(
            path, ffprobe=cfg.video_analysis.ffprobe_path,
        )
    except probe_mod.FFprobeMissing as e:
        return {"mode": "gop", "path": str(path), "sha256": sha,
                "error": str(e)}
    log.log(mode="gop", path=path, sha256=sha,
            size_bytes=path.stat().st_size)
    return {"mode": "gop", "path": str(path), "sha256": sha, **gop}


def _handle_encoder_fingerprint(
    path: Path, cfg: Any, log: HashLogger,
) -> dict[str, Any]:
    sha = sha256_file(path)
    try:
        probe = probe_mod.ffprobe_json(
            path, ffprobe=cfg.video_analysis.ffprobe_path,
        )
    except probe_mod.FFprobeMissing as e:
        return {"mode": "encoder_fingerprint", "path": str(path),
                "sha256": sha, "error": str(e)}
    fp = probe_mod.encoder_fingerprint(probe)
    log.log(mode="encoder_fingerprint", path=path, sha256=sha,
            size_bytes=path.stat().st_size,
            extra={"software_encoder_likely":
                   fp.get("software_encoder_likely", False)})
    return {"mode": "encoder_fingerprint", "path": str(path),
            "sha256": sha, **fp}


def _handle_inspect(path: Path, cfg: Any, log: HashLogger) -> dict[str, Any]:
    """THE two-layer report.

    Container layer:    format_name, atom_order, faststart
                        remux signature, format-level encoder tag
    Elementary-stream:  codec_name, profile, gop, stream-level
                        encoder signals

    NEVER collapsed into one verdict — see the "note" field.
    """
    sha = sha256_file(path)
    a = atoms_mod.parse_top_level_atoms(path)
    sig = atoms_mod.faststart_remux_signature(a)
    try:
        probe = probe_mod.ffprobe_json(
            path, ffprobe=cfg.video_analysis.ffprobe_path,
        )
    except probe_mod.FFprobeMissing:
        probe = {}
    summary = probe_mod.codec_summary(probe) if probe else {"error": "no probe"}
    fp = probe_mod.encoder_fingerprint(probe) if probe else {}
    try:
        gop = probe_mod.gop_structure(
            path, ffprobe=cfg.video_analysis.ffprobe_path,
        )
    except probe_mod.FFprobeMissing:
        gop = {"error": "ffprobe missing"}

    log.log(
        mode="inspect", path=path, sha256=sha,
        size_bytes=path.stat().st_size,
        extra={"moov_before_mdat": sig["moov_before_mdat"]},
    )
    return {
        "mode": "inspect",
        "path": str(path),
        "sha256": sha,
        "container_layer": {
            "format_name": summary.get("format_name"),
            "atom_order": sig["atom_order"],
            "moov_before_mdat": sig["moov_before_mdat"],
            "remux_interpretation": sig["interpretation"],
            "format_encoder_tag": fp.get("format_encoder_tag"),
        },
        "elementary_stream_layer": {
            "codec_name": summary.get("codec_name"),
            "profile": summary.get("profile"),
            "pix_fmt": summary.get("pix_fmt"),
            "width": summary.get("width"),
            "height": summary.get("height"),
            "frame_rate": summary.get("frame_rate"),
            "duration": summary.get("duration"),
            "stream_encoder_tags": fp.get("stream_encoder_tags"),
            "software_encoder_likely":
                fp.get("software_encoder_likely", False),
            "encoder_interpretation": fp.get("interpretation"),
            "gop": gop,
        },
        "note": (
            "Container observations and elementary-stream "
            "observations are reported SEPARATELY on purpose: "
            "a remux pass can touch the container (atom reorder, "
            "metadata restore, faststart) while the underlying "
            "stream is authentic. Do not collapse these into a "
            "single is-it-real verdict — surface signals; weigh "
            "them; never auto-conclude."
        ),
    }


def _do_extract(
    path: Path, *, mode: str, cfg: Any,
    interval_s: float, start: str | None, end: str | None,
    out_dir: Path,
) -> list[Path]:
    va = cfg.video_analysis
    cap = va.max_frames
    ffmpeg_path = va.ffmpeg_path
    if mode == "keyframes":
        return extract_mod.extract_keyframes(
            path, out_dir, ffmpeg=ffmpeg_path,
            max_frames=cap,
        )
    if mode == "sampled":
        return extract_mod.extract_sampled(
            path, out_dir,
            interval_s=interval_s,
            ffmpeg=ffmpeg_path,
            max_frames=cap,
        )
    if mode == "range":
        if not start or not end:
            raise ValueError("extract=range requires start and end")
        return extract_mod.extract_range(
            path, out_dir, start=start, end=end,
            ffmpeg=ffmpeg_path,
            max_frames=cap,
        )
    raise ValueError(f"unknown extract mode {mode!r}")


def _handle_frames(
    path: Path, cfg: Any, log: HashLogger,
    *,
    extract: str,
    interval_s: float,
    start: str | None,
    end: str | None,
    paths: dict[str, Path],
) -> dict[str, Any]:
    sha = sha256_file(path)
    out_dir = paths["frames_root"] / sha[:16]
    try:
        frames = _do_extract(
            path, mode=extract, cfg=cfg,
            interval_s=interval_s, start=start, end=end,
            out_dir=out_dir,
        )
    except extract_mod.FFmpegMissing as e:
        return {"mode": "frames", "path": str(path), "sha256": sha,
                "error": str(e)}
    log.log(
        mode="frames", path=path, sha256=sha,
        size_bytes=path.stat().st_size,
        extra={"extract": extract, "frame_count": len(frames)},
    )
    return {
        "mode": "frames",
        "path": str(path),
        "sha256": sha,
        "extract": extract,
        "frame_count": len(frames),
        "frames": [str(f) for f in frames],
        "out_dir": str(out_dir),
    }


def _handle_analyze(
    path: Path, cfg: Any, log: HashLogger,
    *,
    extract: str,
    interval_s: float,
    start: str | None,
    end: str | None,
    prompt: str,
    provider_fn: ProviderFn | None,
    audio_fn: AudioTranscribeFn | None,
    paths: dict[str, Path],
) -> dict[str, Any]:
    """Extract frames + run vision_analyze describe over each
    one. Composed mode — the frame set + per-frame answers.

    T4-04: also extracts the audio track and transcribes it
    via athena.audio.tools.transcribe_track when an audio_fn
    is available (closes the gap T4-02 originally punted on).
    The transcript lands in the result under ``transcript``
    so the model reasoning over the frames + the transcript
    can align them by timestamp."""
    sha = sha256_file(path)
    out_dir = paths["frames_root"] / sha[:16]
    try:
        frames = _do_extract(
            path, mode=extract, cfg=cfg,
            interval_s=interval_s, start=start, end=end,
            out_dir=out_dir,
        )
    except extract_mod.FFmpegMissing as e:
        return {"mode": "analyze", "path": str(path), "sha256": sha,
                "error": str(e)}
    log.log(
        mode="analyze", path=path, sha256=sha,
        size_bytes=path.stat().st_size,
        extra={"extract": extract, "frame_count": len(frames)},
    )
    if provider_fn is None:
        return {
            "mode": "analyze",
            "path": str(path),
            "sha256": sha,
            "extract": extract,
            "frame_count": len(frames),
            "frames": [str(f) for f in frames],
            "error": (
                "vision provider not available — frames extracted "
                "but per-frame describe was skipped. Use mode=frames "
                "for path-only output, or enable vision_enabled."
            ),
        }

    analyses: list[dict[str, Any]] = []
    for fr in frames:
        try:
            answer = provider_fn(fr, prompt)
        except Exception as e:  # pragma: no cover - provider errors
            logger.warning("vision describe failed on %s: %s", fr, e)
            answer = f"<error: {type(e).__name__}: {e}>"
        analyses.append({"frame": str(fr), "answer": answer})

    result: dict[str, Any] = {
        "mode": "analyze",
        "path": str(path),
        "sha256": sha,
        "extract": extract,
        "frame_count": len(frames),
        "frames_out_dir": str(out_dir),
        "analyses": analyses,
    }

    # T4-04: transcribe the audio track when an audio_fn is
    # available. Defensive — exceptions in the audio path don't
    # break the analyze return; the frames + per-frame describes
    # are still useful on their own.
    if audio_fn is not None:
        try:
            transcript = audio_fn(path)
        except Exception as e:  # noqa: BLE001
            logger.warning("video.analyze: audio transcription raised: %s", e)
            transcript = None
        if transcript is not None:
            result["transcript"] = transcript

    return result


# ---------------------------------------------------------------
# Public entry — registered as @tool below
# ---------------------------------------------------------------


def _run(
    *,
    mode: str,
    path: str | None = None,
    extract: str | None = None,
    interval_s: float | None = None,
    start: str | None = None,
    end: str | None = None,
    prompt: str = "Describe what is happening in this frame.",
    _cfg: Any = None,
    _provider_fn: ProviderFn | None = None,
    _audio_fn: AudioTranscribeFn | None = None,
) -> str:
    """Body of the video_analyze tool, factored out so tests
    call it directly with stubs without going through @tool."""
    cfg = _cfg if _cfg is not None else load_config()
    va = getattr(cfg, "video_analysis", None)
    if va is not None and not va.enabled:
        return json.dumps({
            "error": "cfg.video_analysis.enabled=False; operator disabled video_analyze",
            "mode": mode,
        })
    if mode not in VALID_MODES:
        return json.dumps({
            "error": f"unknown mode {mode!r}; choose from {list(VALID_MODES)}",
            "mode": mode,
        })
    if not path:
        return json.dumps({"error": "path is required", "mode": mode})
    p = Path(path)
    if not p.exists():
        return json.dumps({"error": f"file not found: {path}", "mode": mode})

    paths_resolved = _resolve_paths(cfg)
    log = HashLogger(paths_resolved["audit"])

    chosen_extract = extract or (
        va.default_extract if va is not None else "keyframes"
    )
    if chosen_extract not in VALID_EXTRACT:
        return json.dumps({
            "error": f"unknown extract {chosen_extract!r}; "
                     f"choose from {list(VALID_EXTRACT)}",
            "mode": mode,
        })
    interval = (
        interval_s if interval_s is not None
        else (va.sampled_interval_s if va is not None else 5.0)
    )

    try:
        if mode == "probe":
            return json.dumps(_handle_probe(p, cfg, log))
        if mode == "atoms":
            return json.dumps(_handle_atoms(p, log))
        if mode == "gop":
            return json.dumps(_handle_gop(p, cfg, log))
        if mode == "encoder_fingerprint":
            return json.dumps(_handle_encoder_fingerprint(p, cfg, log))
        if mode == "inspect":
            return json.dumps(_handle_inspect(p, cfg, log))
        if mode == "frames":
            return json.dumps(_handle_frames(
                p, cfg, log,
                extract=chosen_extract, interval_s=interval,
                start=start, end=end, paths=paths_resolved,
            ))
        if mode == "analyze":
            fn = _provider_fn or _default_provider_fn(cfg)
            afn = (
                _audio_fn if _audio_fn is not None
                else _default_audio_transcribe_fn(cfg)
            )
            return json.dumps(_handle_analyze(
                p, cfg, log,
                extract=chosen_extract, interval_s=interval,
                start=start, end=end, prompt=prompt,
                provider_fn=fn, audio_fn=afn,
                paths=paths_resolved,
            ))
    except ValueError as e:
        return json.dumps({"error": str(e), "mode": mode})
    except Exception as e:
        logger.exception("video_analyze mode=%s failed", mode)
        return json.dumps({"error": f"{type(e).__name__}: {e}", "mode": mode})

    return json.dumps({"error": "unhandled mode", "mode": mode})


# ---------------------------------------------------------------
# @tool registration
# ---------------------------------------------------------------


from ..tools.registry import tool  # noqa: E402 — late import to avoid cycles


@tool(
    name="video_analyze",
    toolset="vision",
    description=(
        "Analyse a video. Seven modes, two-layer discipline:\n"
        "  probe                 ffprobe codec / format summary.\n"
        "  atoms                 MP4/MOV box ordering + faststart\n"
        "                        remux signature (pure-Python, no\n"
        "                        ffmpeg needed for this mode).\n"
        "  gop                   I/P/B frame-type pattern +\n"
        "                        keyframe intervals.\n"
        "  encoder_fingerprint   x264/x265 tag detection with\n"
        "                        HEDGED interpretation. Absence is\n"
        "                        NOT proof of hardware encoding.\n"
        "  inspect               THE FULL REPORT — container layer\n"
        "                        (atoms, format, faststart) and\n"
        "                        elementary-stream layer (codec,\n"
        "                        GOP, encoder signals) reported\n"
        "                        SEPARATELY. A remux can touch\n"
        "                        the container while the stream\n"
        "                        is authentic. Surface signals,\n"
        "                        weigh them, never auto-conclude.\n"
        "  frames                Extract keyframes / sampled /\n"
        "                        range PNG frames; returns paths.\n"
        "  analyze               Extract + route each frame through\n"
        "                        vision_analyze describe; returns\n"
        "                        per-frame answers."
    ),
    parameters={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": list(VALID_MODES),
            },
            "path": {
                "type": "string",
                "description": "Path to the video file.",
            },
            "extract": {
                "type": "string",
                "enum": list(VALID_EXTRACT),
                "description": (
                    "Frame extraction strategy; only used by mode "
                    "= frames or analyze. Default keyframes."
                ),
            },
            "interval_s": {
                "type": "number",
                "description": (
                    "Sampled-extract interval (seconds). Only used "
                    "when extract=sampled. Default 5."
                ),
            },
            "start": {
                "type": "string",
                "description": (
                    "Start timestamp (HH:MM:SS or seconds); only "
                    "extract=range."
                ),
            },
            "end": {
                "type": "string",
                "description": (
                    "End timestamp; only extract=range."
                ),
            },
            "prompt": {
                "type": "string",
                "description": (
                    "Per-frame prompt for mode=analyze. Default "
                    "describes what's happening in the frame."
                ),
            },
        },
        "required": ["mode", "path"],
    },
)
def video_analyze(**kwargs: Any) -> str:
    return _run(**kwargs)
