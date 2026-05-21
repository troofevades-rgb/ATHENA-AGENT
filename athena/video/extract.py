"""ffmpeg-backed frame extraction (T4-02.4).

Three extraction modes:

  extract_keyframes(path, out_dir, *, max_frames)
      I-frames only (``-skip_frame nokey``). Cheap, and key-
      frames are where scene content actually lives.

  extract_sampled(path, out_dir, *, interval_s, max_frames)
      One frame every N seconds (``-vf fps=1/N``). Useful for
      long videos where keyframes are too sparse to summarise
      the content.

  extract_range(path, out_dir, *, start, end, max_frames)
      Every frame between two timestamps (``-ss`` / ``-to``).
      Used for "show me what happens at 1:23".

Every call:
  - rejects when ffmpeg isn't on PATH (FFmpegMissing — clear
    install hint)
  - caps the output at ``max_frames`` (default 200 — long
    videos in ``extract_all`` mode would explode disk
    otherwise; the cap is enforced via ``-frames:v``)
  - writes PNGs to ``out_dir`` (created if absent) and returns
    the sorted list of paths
  - returns ``[]`` on ffmpeg failure rather than raising — the
    analyze layer composes this alongside the inspect modes,
    and one extraction failure shouldn't break the whole call

The returned frames are then routed through T4-01's
``vision_analyze`` describe mode for per-frame reasoning. The
two layers (frame extraction + per-frame analysis) are kept
separate so a host without a multimodal model can still
extract frames for downstream tools, and a host without
ffmpeg can still call the analyze module on a pre-extracted
PNG.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class FFmpegMissing(RuntimeError):
    """Raised when ffmpeg is not on PATH or refuses to run."""


def _require_ffmpeg(ffmpeg: str) -> None:
    if not shutil.which(ffmpeg):
        raise FFmpegMissing(
            f"{ffmpeg!r} not found on PATH — install ffmpeg "
            "(brew install ffmpeg / apt install ffmpeg / "
            "scoop install ffmpeg)"
        )


def _run(args: list[str], *, timeout: float) -> int:
    try:
        proc = subprocess.run(
            args, capture_output=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg timed out: %s", args[:4])
        return 124
    if proc.returncode != 0:
        logger.warning(
            "ffmpeg exited %d for %s — stderr: %s",
            proc.returncode, args[:4],
            proc.stderr.decode("utf-8", errors="replace")[:400],
        )
    return proc.returncode


def extract_keyframes(
    path: Path | str,
    out_dir: Path | str,
    *,
    ffmpeg: str = "ffmpeg",
    max_frames: int = 200,
    timeout: float = 300.0,
) -> list[Path]:
    """Extract I-frames (keyframes) as PNGs into ``out_dir``."""
    _require_ffmpeg(ffmpeg)
    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir_p / "kf_%05d.png")
    _run(
        [
            ffmpeg, "-y",
            "-skip_frame", "nokey",
            "-i", str(path),
            "-vsync", "vfr",
            "-frame_pts", "true",
            "-frames:v", str(max_frames),
            pattern,
        ],
        timeout=timeout,
    )
    return sorted(out_dir_p.glob("kf_*.png"))


def extract_sampled(
    path: Path | str,
    out_dir: Path | str,
    *,
    interval_s: float,
    ffmpeg: str = "ffmpeg",
    max_frames: int = 200,
    timeout: float = 300.0,
) -> list[Path]:
    """Extract one frame every ``interval_s`` seconds."""
    if interval_s <= 0:
        raise ValueError(f"interval_s must be > 0, got {interval_s}")
    _require_ffmpeg(ffmpeg)
    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir_p / "s_%05d.png")
    _run(
        [
            ffmpeg, "-y",
            "-i", str(path),
            "-vf", f"fps=1/{interval_s}",
            "-frames:v", str(max_frames),
            pattern,
        ],
        timeout=timeout,
    )
    return sorted(out_dir_p.glob("s_*.png"))


def extract_range(
    path: Path | str,
    out_dir: Path | str,
    *,
    start: str,
    end: str,
    ffmpeg: str = "ffmpeg",
    max_frames: int = 200,
    timeout: float = 300.0,
) -> list[Path]:
    """Extract every frame between ``start`` and ``end`` (HH:MM:SS
    or float-seconds timestamps)."""
    _require_ffmpeg(ffmpeg)
    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir_p / "r_%05d.png")
    _run(
        [
            ffmpeg, "-y",
            "-ss", str(start), "-to", str(end),
            "-i", str(path),
            "-frames:v", str(max_frames),
            pattern,
        ],
        timeout=timeout,
    )
    return sorted(out_dir_p.glob("r_*.png"))
