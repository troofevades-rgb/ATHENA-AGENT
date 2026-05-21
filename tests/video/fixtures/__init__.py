"""Video fixtures — synthesised at test-collection time when
ffmpeg is available; otherwise tests that need them skip
cleanly.

Six tiny fixtures (each <100 KB so the cost is negligible):

  camera_original.mp4   — 2s clip muxed with mdat BEFORE moov
                          (simulates an unflushed camera capture)
  faststart.mp4         — same clip rewritten with
                          ``ffmpeg -movflags +faststart``
                          (moov BEFORE mdat — the qt-faststart tell)
  x264_encoded.mp4      — explicitly libx264-encoded (carries the
                          x264 metadata tag)
  sample.mp4            — short clip for frame-extraction tests
                          (the keyframe + sampled + range modes)
  generated.mp4         — a "synthetic" clip generated wholly by
                          a software encoder (x264) — used by the
                          encoder-fingerprint test
  short.mp4             — a 1-second 320x240 clip; fast smoke target

Like the vision fixtures (tests/vision/fixtures/__init__.py),
these are gitignored — building them needs ffmpeg, and on a
host without ffmpeg the consumer tests skip via
``pytest.importorskip("...")`` / ``shutil.which`` guards.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def have_ffprobe() -> bool:
    return shutil.which("ffprobe") is not None


def _run(cmd: list[str]) -> None:
    subprocess.run(
        cmd, capture_output=True, timeout=60, check=False,
    )


def _gen_base_clip(out: Path, *, encoder: str = "libx264",
                   duration: float = 2.0,
                   w: int = 320, h: int = 240,
                   fps: int = 24,
                   faststart: bool = False) -> None:
    """Generate a synthetic clip using ffmpeg's testsrc filter —
    deterministic, no real-world content, tiny."""
    args: list[str] = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration}:size={w}x{h}:rate={fps}",
        "-c:v", encoder,
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
    ]
    if faststart:
        args.extend(["-movflags", "+faststart"])
    args.append(str(out))
    _run(args)


def ensure_fixtures() -> dict[str, Path]:
    """Build any missing fixtures. Returns the path map. No-op
    (returns the map) when every file already exists."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    paths = {
        "camera_original": FIXTURES_DIR / "camera_original.mp4",
        "faststart": FIXTURES_DIR / "faststart.mp4",
        "x264_encoded": FIXTURES_DIR / "x264_encoded.mp4",
        "sample": FIXTURES_DIR / "sample.mp4",
        "generated": FIXTURES_DIR / "generated.mp4",
        "short": FIXTURES_DIR / "short.mp4",
    }
    if not have_ffmpeg():
        return paths  # caller must check have_ffmpeg before consuming
    if not paths["camera_original"].exists():
        _gen_base_clip(paths["camera_original"], faststart=False)
    if not paths["faststart"].exists():
        _gen_base_clip(paths["faststart"], faststart=True)
    if not paths["x264_encoded"].exists():
        _gen_base_clip(paths["x264_encoded"], encoder="libx264")
    if not paths["sample"].exists():
        _gen_base_clip(paths["sample"], duration=3.0)
    if not paths["generated"].exists():
        # An explicit x264 + faststart combo for the
        # encoder-fingerprint AND the remux-tells together
        _gen_base_clip(paths["generated"], encoder="libx264",
                       faststart=True)
    if not paths["short"].exists():
        _gen_base_clip(paths["short"], duration=1.0)
    return paths


if __name__ == "__main__":
    out = ensure_fixtures()
    for k, v in out.items():
        size = v.stat().st_size if v.exists() else 0
        print(f"{k:18s} {size:>9d}  {v}")
