"""Vision fixtures — synthesised at test-collection time.

Tests in ``tests/vision`` import :func:`ensure_fixtures` (lazy
build) so we never ship binary blobs in the repo and fixtures
stay reproducible across machines / CI / Windows-vs-Linux. The
generator uses Pillow + raw byte-level EXIF injection so it has
no dependency on piexif or external tools.

Files produced under :data:`FIXTURES_DIR`:

  original.jpg     — 800x600 photo-ish content with a synthetic
                     EXIF block carrying Make/Model/DateTime
  stripped.jpg     — same pixels, no EXIF
  edited.jpg       — original with a 80x80 painted patch at (200,200)
  recompressed.jpg — original re-saved at quality 70
  large.png        — 2400x1200 (>2000px long edge)
  small.png        — 320x240 (<500px)
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw

FIXTURES_DIR = Path(__file__).parent


def _draw_photo(w: int, h: int, *, seed: int) -> Image.Image:
    """Deterministic 'photo-ish' content — gradient sky + a few
    coloured shapes. Stable across machines because we seed the
    RNG."""
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h), (200, 220, 240))
    draw = ImageDraw.Draw(img)
    # Sky-to-ground vertical gradient
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(200 * (1 - t) + 90 * t)
        g = int(220 * (1 - t) + 130 * t)
        b = int(240 * (1 - t) + 80 * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    # A horizon "sun"
    cx, cy = int(w * 0.7), int(h * 0.3)
    draw.ellipse([cx - 60, cy - 60, cx + 60, cy + 60], fill=(255, 230, 130))
    # Some deterministic "trees" so pHash has structure to grip
    for _ in range(8):
        x = rng.randint(40, w - 60)
        y = rng.randint(int(h * 0.55), h - 80)
        draw.rectangle([x - 8, y, x + 8, y + 40], fill=(80, 50, 30))
        draw.ellipse([x - 28, y - 40, x + 28, y + 10], fill=(40, 110, 60))
    return img


def _build_synthetic_exif() -> Image.Exif:
    """Build a minimal EXIF object with Make / Model / DateTime.

    Returned as :class:`PIL.Image.Exif` (the only shape that
    survives ``Image.save(exif=...)`` round-trip on JPEG —
    raw bytes get silently stripped by Pillow's JPEG encoder).
    """
    ex = Image.Exif()
    ex[0x010F] = "AthenaCam"        # Make
    ex[0x0110] = "T4-01"            # Model
    ex[0x0132] = "2026:05:20 12:34:56"  # DateTime
    return ex


def _ensure_path(p: Path, builder) -> None:
    if p.exists() and p.stat().st_size > 0:
        return
    builder(p)


def _write_original(p: Path) -> None:
    img = _draw_photo(800, 600, seed=1)
    exif = _build_synthetic_exif()
    img.save(p, format="JPEG", quality=92, exif=exif)


def _write_stripped(p: Path) -> None:
    img = _draw_photo(800, 600, seed=1)
    img.save(p, format="JPEG", quality=92)


def _write_edited(p: Path) -> None:
    img = _draw_photo(800, 600, seed=1)
    draw = ImageDraw.Draw(img)
    # A bright spliced patch — ELA should light this region up
    draw.rectangle([200, 200, 280, 280], fill=(255, 20, 200))
    img.save(p, format="JPEG", quality=92)


def _write_recompressed(p: Path) -> None:
    original = FIXTURES_DIR / "original.jpg"
    if not original.exists():
        _write_original(original)
    img = Image.open(original)
    img.save(p, format="JPEG", quality=70)


def _write_large(p: Path) -> None:
    img = _draw_photo(2400, 1200, seed=2)
    img.save(p, format="PNG")


def _write_small(p: Path) -> None:
    img = _draw_photo(320, 240, seed=3)
    img.save(p, format="PNG")


def ensure_fixtures() -> dict[str, Path]:
    """Lazy idempotent build. Returns the path map."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    paths = {
        "original": FIXTURES_DIR / "original.jpg",
        "stripped": FIXTURES_DIR / "stripped.jpg",
        "edited": FIXTURES_DIR / "edited.jpg",
        "recompressed": FIXTURES_DIR / "recompressed.jpg",
        "large": FIXTURES_DIR / "large.png",
        "small": FIXTURES_DIR / "small.png",
    }
    _ensure_path(paths["original"], _write_original)
    _ensure_path(paths["stripped"], _write_stripped)
    _ensure_path(paths["edited"], _write_edited)
    _ensure_path(paths["recompressed"], _write_recompressed)
    _ensure_path(paths["large"], _write_large)
    _ensure_path(paths["small"], _write_small)
    return paths


if __name__ == "__main__":
    out = ensure_fixtures()
    for k, v in out.items():
        size = v.stat().st_size if v.exists() else 0
        print(f"{k:14s} {size:>8d}  {v}")
