"""audio_analyze tool (T4-04.2).

One tool, four modes:

  transcribe   text + segment timestamps
  diarize      transcribe + speaker labels (opt-in; backend
               must declare diarization support — faster-whisper
               doesn't, so segments come back with speaker=None
               and that's the contract)
  classify     coarse content type (speech / music / silence /
               mixed / unknown)
  full         all of the above

Every read sha256s the input audio file and writes a JSONL
audit row + a transcript artifact (text or JSON) under
``cfg.audio_output_dir`` (default ``<profile_dir>/audio/``).
Same provenance shape as T4-01 vision and T4-02 video.

Long-audio handling: files > ``cfg.audio_chunk_seconds`` are
chunked with ``cfg.audio_chunk_overlap_s`` seconds of overlap
and stitched (the overlapping segments at chunk seams are
de-duplicated so words aren't dropped). The stitch fixes
absolute timestamps by passing ``chunk_offset_s`` to the
backend.

Composable helper: ``transcribe_track(path, *, cfg=...,
backend=...)`` is the path T4-02 video uses to transcribe an
extracted audio stream. Returns the same :class:`TranscribeResult`
shape; bypasses the tool layer's JSON formatting.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any, Callable

from ..config import load_config, profile_dir
from ..tools.registry import tool
from ..vision.hashlog import HashLogger, audit_path, sha256_file
from .job import AudioBackend, ContentType, Segment, TranscribeResult

logger = logging.getLogger(__name__)


VALID_MODES = ("transcribe", "diarize", "classify", "full")


_AUDIO_AUDIT_FILENAME = "audio_audit.jsonl"


def audio_audit_path(profile_dir_path: Path | str) -> Path:
    return Path(profile_dir_path) / _AUDIO_AUDIT_FILENAME


# ---------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------


def _resolve_paths(cfg: Any) -> dict[str, Path]:
    pdir = profile_dir(getattr(cfg, "profile", "default"))
    out_dir = (
        Path(cfg.audio_output_dir)
        if getattr(cfg, "audio_output_dir", None)
        else pdir / "audio"
    )
    return {
        "profile": pdir,
        "audit": audio_audit_path(pdir),
        "out_dir": out_dir,
    }


# ---------------------------------------------------------------
# Backend resolution
# ---------------------------------------------------------------


def _resolve_backend(cfg: Any) -> AudioBackend | None:
    """Find the audio backend via the T5-05 broker. Returns
    None when no provider declares ``audio_transcription`` or
    the chosen class can't be constructed."""
    # Import the backends package so registrations fire.
    from . import backends  # noqa: F401
    from ..media.registry import MediaRegistry

    reg = MediaRegistry(cfg=cfg)
    cls = reg.backend_for("audio_transcription")
    if cls is None:
        logger.info("audio: no backend declares audio_transcription")
        return None
    try:
        instance = cls()
    except Exception as e:  # noqa: BLE001
        logger.warning("audio: backend %r failed to construct: %s", cls.__name__, e)
        return None
    if not hasattr(instance, "transcribe"):
        logger.warning(
            "audio: backend %r does not implement transcribe()", cls.__name__,
        )
        return None
    return instance  # type: ignore[return-value]


# ---------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------


def _audio_duration_s(path: Path) -> float | None:
    """Cheap duration read. Tries WAV header first (pure
    stdlib); falls back to ffprobe when available. Returns
    None on failure — the chunker treats unknown duration as
    "process as one chunk" rather than risking a bad split."""
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / max(1, w.getframerate())
    except Exception:  # noqa: BLE001
        pass
    if shutil.which("ffprobe"):
        try:
            out = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    str(path),
                ],
                capture_output=True, text=True, timeout=20,
            )
            data = json.loads(out.stdout) if out.stdout.strip() else {}
            dur = data.get("format", {}).get("duration")
            if dur is not None:
                return float(dur)
        except Exception:  # noqa: BLE001
            pass
    return None


def _chunk_boundaries(
    duration_s: float,
    *,
    chunk_s: float,
    overlap_s: float,
) -> list[tuple[float, float]]:
    """Produce overlapping chunk windows.

    Each chunk except the first starts ``overlap_s`` before
    the previous chunk's end so words at the seam appear in
    both windows. The stitcher de-duplicates segments in the
    overlap region.

    Returns ``[(start, end), ...]`` in seconds. Always returns
    at least one chunk; clamps ``end`` at ``duration_s``.
    """
    if chunk_s <= 0:
        return [(0.0, duration_s)]
    if duration_s <= chunk_s:
        return [(0.0, duration_s)]

    out: list[tuple[float, float]] = []
    start = 0.0
    step = max(0.1, chunk_s - max(0.0, overlap_s))
    while start < duration_s:
        end = min(start + chunk_s, duration_s)
        out.append((start, end))
        if end >= duration_s:
            break
        start += step
    return out


def _stitch(
    chunk_results: list[TranscribeResult],
    *,
    chunk_windows: list[tuple[float, float]],
    overlap_s: float,
) -> TranscribeResult:
    """Merge per-chunk results into one. Segments are already
    in absolute file-seconds (the backend honored
    chunk_offset_s). The dedupe rule: a segment whose start
    falls inside the previous chunk's "tail overlap window"
    AND whose text repeats the last segment we kept is skipped.
    Cheap + robust to small floating-point drift at seams.
    """
    if not chunk_results:
        return TranscribeResult(segments=[])
    if len(chunk_results) == 1:
        return chunk_results[0]

    out_segments: list[Segment] = []
    seen_keys: set[tuple[float, str]] = set()
    last_text: str | None = None

    for idx, res in enumerate(chunk_results):
        prev_end = chunk_windows[idx - 1][1] if idx > 0 else 0.0
        for seg in res.segments:
            in_overlap = (
                idx > 0
                and seg.start < prev_end
                and seg.start >= max(0.0, prev_end - overlap_s)
            )
            # Cheap key — rounded start + text — to recognise
            # the same segment surfacing in two adjacent chunks.
            key = (round(seg.start, 1), seg.text.strip().lower())
            if in_overlap and (key in seen_keys or seg.text.strip() == (last_text or "")):
                continue
            out_segments.append(seg)
            seen_keys.add(key)
            last_text = seg.text.strip()

    # Carry language from the first chunk that detected one;
    # use the LAST chunk's duration (the absolute end of audio).
    lang = next(
        (r.language for r in chunk_results if r.language),
        None,
    )
    return TranscribeResult(
        segments=out_segments,
        language=lang,
        duration=chunk_windows[-1][1],
    )


# ---------------------------------------------------------------
# transcribe_track — composable helper for T4-02 video
# ---------------------------------------------------------------


def transcribe_track(
    path: Path | str,
    *,
    cfg: Any | None = None,
    backend: AudioBackend | None = None,
    language: str | None = None,
    diarize: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> TranscribeResult:
    """Transcribe a single audio file end-to-end with chunking.

    Used by T4-02 video's ``analyze`` mode to transcribe an
    extracted audio stream + align segments to frame timestamps.
    Bypasses the tool layer's JSON formatting — returns the raw
    :class:`TranscribeResult` so the caller composes naturally.

    Long files chunked according to ``cfg.audio_chunk_seconds``
    + ``cfg.audio_chunk_overlap_s``. ``progress(done, total)``
    is called after each chunk so a CLI surface can show "3/12
    chunks transcribed".
    """
    cfg = cfg if cfg is not None else load_config()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"audio file not found: {path}")

    if backend is None:
        backend = _resolve_backend(cfg)
    if backend is None:
        return TranscribeResult(segments=[])

    duration = _audio_duration_s(p)
    chunk_s = float(getattr(cfg, "audio_chunk_seconds", 30.0))
    overlap_s = float(getattr(cfg, "audio_chunk_overlap_s", 2.0))

    if duration is None or duration <= chunk_s:
        # Single-shot — no chunking, no offset.
        if progress is not None:
            progress(1, 1)
        return backend.transcribe(
            p, language=language, diarize=diarize, chunk_offset_s=0.0,
        )

    windows = _chunk_boundaries(duration, chunk_s=chunk_s, overlap_s=overlap_s)
    chunks: list[TranscribeResult] = []
    for i, (start, _end) in enumerate(windows, start=1):
        res = backend.transcribe(
            p, language=language, diarize=diarize, chunk_offset_s=start,
        )
        chunks.append(res)
        if progress is not None:
            progress(i, len(windows))

    stitched = _stitch(chunks, chunk_windows=windows, overlap_s=overlap_s)
    if stitched.duration is None and duration is not None:
        stitched = TranscribeResult(
            segments=stitched.segments,
            language=stitched.language,
            duration=duration,
            content_type=stitched.content_type,
        )
    return stitched


# ---------------------------------------------------------------
# Transcript artifact writer
# ---------------------------------------------------------------


def _write_transcript(
    result: TranscribeResult,
    *,
    out_dir: Path,
    source_sha: str,
    source_path: Path,
) -> Path:
    """Write the transcript artifact to ``out_dir`` as JSON +
    a sidecar plaintext for grep-friendliness. Returns the
    JSON path; the .txt sibling is a derived artifact."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{source_path.stem}_{source_sha[:8]}"
    json_path = out_dir / f"{stem}.json"
    txt_path = out_dir / f"{stem}.txt"

    json_path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    lines = [
        f"[{s.start:7.2f}-{s.end:7.2f}] "
        + (f"{s.speaker}: " if s.speaker else "")
        + s.text
        for s in result.segments
    ]
    txt_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return json_path


# ---------------------------------------------------------------
# Public entry — registered as @tool below
# ---------------------------------------------------------------


def _run(
    *,
    path: str | None = None,
    mode: str = "transcribe",
    language: str | None = None,
    _cfg: Any = None,
    _backend: AudioBackend | None = None,
    _progress: Callable[[int, int], None] | None = None,
) -> str:
    cfg = _cfg if _cfg is not None else load_config()
    if not getattr(cfg, "audio_analyze_enabled", True):
        return json.dumps({
            "available": False,
            "error": "audio_analyze_enabled=False; operator disabled audio_analyze",
            "mode": mode,
        })
    if mode not in VALID_MODES:
        return json.dumps({
            "available": False,
            "error": f"unknown mode {mode!r}; choose from {list(VALID_MODES)}",
            "mode": mode,
        })
    if not path:
        return json.dumps({
            "available": False, "error": "path is required", "mode": mode,
        })
    p = Path(path)
    if not p.exists():
        return json.dumps({
            "available": False,
            "error": f"file not found: {path}",
            "mode": mode,
        })

    backend = _backend if _backend is not None else _resolve_backend(cfg)
    if backend is None:
        return json.dumps({
            "available": False,
            "mode": mode,
            "reason": (
                "no audio backend configured — declare an "
                "audio_transcription-capable provider (e.g. "
                "faster-whisper) or set cfg.audio_analyze_enabled=False"
            ),
        })

    paths = _resolve_paths(cfg)
    log = HashLogger(paths["audit"])
    sha = sha256_file(p)

    diarize = (
        mode in ("diarize", "full")
        and bool(getattr(cfg, "audio_diarization_enabled", False))
    )

    try:
        result = transcribe_track(
            p, cfg=cfg, backend=backend,
            language=language, diarize=diarize,
            progress=_progress,
        )
    except FileNotFoundError as e:
        return json.dumps({
            "available": False, "error": str(e), "mode": mode,
        })
    except Exception as e:  # noqa: BLE001
        logger.exception("audio_analyze: transcribe failed")
        return json.dumps({
            "available": True,
            "error": f"transcribe failed: {type(e).__name__}: {e}",
            "mode": mode,
            "path": str(p), "sha256": sha,
        })

    if mode in ("classify", "full"):
        try:
            result = TranscribeResult(
                segments=result.segments,
                language=result.language,
                duration=result.duration,
                content_type=backend.classify(p),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("audio_analyze: classify failed: %s", e)

    transcript_path = _write_transcript(
        result, out_dir=paths["out_dir"],
        source_sha=sha, source_path=p,
    )

    log.log(
        mode=mode, path=p, sha256=sha,
        size_bytes=p.stat().st_size,
        extra={
            "segment_count": len(result.segments),
            "language": result.language,
            "duration": result.duration,
            "transcript_path": str(transcript_path),
            "diarize": diarize,
        },
    )

    return json.dumps({
        "available": True,
        "mode": mode,
        "path": str(p),
        "sha256": sha,
        "transcript_path": str(transcript_path),
        **result.to_dict(),
    })


@tool(
    name="audio_analyze",
    toolset="vision",  # same toolset as vision / video; the model
                       # sees them grouped under "media analysis"
    description=(
        "Transcribe an audio file. Modes:\n"
        "  transcribe — text + segment timestamps (default)\n"
        "  diarize    — transcribe + speaker labels per segment\n"
        "               (requires cfg.audio_diarization_enabled +\n"
        "               a backend that supports diarization; with\n"
        "               faster-whisper, returns segments with\n"
        "               speaker=null since the default backend\n"
        "               doesn't ship a diarizer)\n"
        "  classify   — coarse content type (speech/music/silence)\n"
        "  full       — all of the above\n"
        "Long files are automatically chunked + stitched. Every\n"
        "read writes a transcript artifact under\n"
        "<profile>/audio/ and a JSONL audit row to\n"
        "<profile>/audio_audit.jsonl."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "mode": {
                "type": "string",
                "enum": list(VALID_MODES),
            },
            "language": {
                "type": "string",
                "description": (
                    "Optional ISO-639-1 language hint (e.g. 'en', "
                    "'fr'). Omit to let the backend auto-detect."
                ),
            },
        },
        "required": ["path"],
    },
)
def audio_analyze(**kwargs: Any) -> str:
    return _run(**kwargs)
