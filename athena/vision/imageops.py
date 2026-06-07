"""Local image operations for vision_analyze (T4-01.3).

Pure-Pillow / imagehash pixel ops. No network, no provider
dispatch — every function here runs locally and is safe to call
on untrusted images (Pillow has its own bombs-and-overflow
checks; we add a max-pixel guard on top so a crafted PNG can't
exhaust memory).

Public surface (all sync, all deterministic for fixed inputs):

  extract_exif(path)             -> dict[str, str | int]
  error_level_analysis(path, *,
       quality=80, threshold=15)
                                 -> dict (regions, summary)
  crop_region(path, *, box,
       out_dir, return_b64=False)
                                 -> dict (out_path, sha256, b64?)
  histogram(path)                -> dict (per-channel + bucket bins)
  perceptual_hash(path,
       algorithm="phash",
       hash_size=8)              -> dict (hex, algorithm)
  phash_distance(h1, h2)         -> int (hamming distance)
  metadata_strip_check(orig,
       suspect)                  -> dict (verdict, missing_keys)

Each function reads the file once, runs the op, and returns a
JSON-safe dict — the tool layer above logs the file's sha256
to the hash-log and forwards the dict back to the model.

Caveats baked into the docstrings:

  - ELA is a SIGNAL, not a verdict. A bright region in the ELA
    map means "this region's JPEG compression-level differs from
    its neighbours" — most edits show, but some don't (uniform
    flat regions, very low quality input, double-compressed
    forgeries that match the host's quality).

  - pHash is robust to mild crops / resizes / re-encodes but not
    to extreme transforms. Distance ≤ 8 is a strong match;
    8–16 is similar; > 16 is "probably different scenes".

  - EXIF readers see what Pillow's Image.Exif returns. piexif
    or exiftool would surface more keys (MakerNote, GPS sub-IFD)
    — left as a documented gap, not a hard dependency.
"""

from __future__ import annotations

import dataclasses
import io
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import imagehash
from PIL import Image, ImageChops

# Cap on input dimensions to refuse decompression-bomb shaped
# inputs. Pillow has its own DECOMPRESSION_BOMB warning around
# ~89 Mpx; we set ours lower for analysis ops because the local
# screenshot fixture path already screens for sane sizes and a
# crafted 1 GB PNG should be rejected, not loaded.
MAX_INPUT_PIXELS = 80 * 1_000_000  # 80 Mpx


# ---------------------------------------------------------------
# helpers
# ---------------------------------------------------------------


def _open_safely(path: Path | str) -> Image.Image:
    """Open + validate. Raises ValueError on oversize input."""
    img = Image.open(Path(path))
    img.load()  # force decode so a corrupt file fails here, not later
    w, h = img.size
    if w * h > MAX_INPUT_PIXELS:
        raise ValueError(
            f"image too large: {w}x{h} = {w * h:,} px exceeds MAX_INPUT_PIXELS={MAX_INPUT_PIXELS:,}"
        )
    return img


# Mapping of common EXIF tag IDs to friendlier names. We only
# decode the keys that journalism / provenance reviewers care
# about most — date/time/make/model/orientation/software/lens —
# and pass everything else through under its numeric tag.
_EXIF_NAMES: dict[int, str] = {
    0x010F: "Make",
    0x0110: "Model",
    0x0112: "Orientation",
    0x011A: "XResolution",
    0x011B: "YResolution",
    0x0128: "ResolutionUnit",
    0x0131: "Software",
    0x0132: "DateTime",
    0x013B: "Artist",
    0x8298: "Copyright",
    0x9003: "DateTimeOriginal",
    0x9004: "DateTimeDigitized",
    0x9201: "ShutterSpeedValue",
    0x9202: "ApertureValue",
    0x9207: "MeteringMode",
    0x9209: "Flash",
    0x920A: "FocalLength",
    0xA002: "PixelXDimension",
    0xA003: "PixelYDimension",
    0xA40A: "Sharpness",
    0xA433: "LensMake",
    0xA434: "LensModel",
    0xA435: "LensSerialNumber",
    0x8825: "GPSInfo",
}


# ---------------------------------------------------------------
# EXIF
# ---------------------------------------------------------------


def extract_exif(path: Path | str) -> dict[str, Any]:
    """Return a JSON-safe EXIF dict.

    Keys are friendly names when known (e.g. ``"DateTime"``,
    ``"Make"``); otherwise stringified hex tag (``"0x0143"``).
    Values are stringified — Pillow returns bytes / Fraction /
    tuples for various tags and we normalise to JSON-safe shapes.

    Returns ``{}`` (not raise) when the file has no EXIF. Callers
    above this layer distinguish "no metadata" from "couldn't
    open" by the absence of the file open succeeding.
    """
    img = _open_safely(path)
    exif = img.getexif()
    if not exif:
        return {}
    out: dict[str, Any] = {}
    for tag, val in exif.items():
        key = _EXIF_NAMES.get(tag, f"0x{tag:04X}")
        out[key] = _normalise_exif_value(val)
    return out


def _normalise_exif_value(v: Any) -> Any:
    """Coerce one EXIF value into a JSON-serializable shape."""
    if isinstance(v, bytes):
        try:
            return v.decode("ascii", errors="replace").rstrip("\x00")
        except UnicodeDecodeError:
            return v.hex()
    if isinstance(v, (tuple, list)):
        return [_normalise_exif_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _normalise_exif_value(x) for k, x in v.items()}
    # IFDRational / Fraction style — convert to float if possible.
    if hasattr(v, "numerator") and hasattr(v, "denominator"):
        try:
            return float(v)
        except (TypeError, ZeroDivisionError):
            return f"{v.numerator}/{v.denominator}"
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return str(v)


# ---------------------------------------------------------------
# Error Level Analysis (ELA)
# ---------------------------------------------------------------


def error_level_analysis(
    path: Path | str,
    *,
    quality: int = 80,
    threshold: int = 15,
) -> dict[str, Any]:
    """Compute an ELA signal map for a JPEG/PNG.

    The classical ELA recipe:
      1. Decode the input.
      2. Re-encode at ``quality`` (default 80).
      3. Diff the two decodes — pixels that compress *differently*
         from their neighbours are interesting.
      4. Report the bounding regions whose maximum diff exceeds
         ``threshold``.

    Returns::

      {
        "quality": 80,
        "threshold": 15,
        "max_diff": int (0..255),
        "mean_diff": float,
        "patches": [
          {"box": [x0, y0, x1, y1], "max_diff": int,
           "mean_diff": float},
          ...
        ]
      }

    Notes for the model (also surfaced in docs/reference):

      - High overall ``max_diff`` does NOT mean tampered — it
        commonly means the input is a high-quality original
        compared against an 80-q re-encode. The signal is in the
        *contrast* between regions.
      - PNGs and other lossless inputs give noisier ELA because
        every pixel is "freshly compressed" by the q=80 pass.
      - This is a HEURISTIC, not a verdict. Pair with EXIF +
        pHash for triangulation.
    """
    if not 1 <= quality <= 100:
        raise ValueError(f"quality must be in 1..100, got {quality}")
    if threshold < 0:
        raise ValueError("threshold must be >= 0")

    img = _open_safely(path).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    recomp = Image.open(buf).convert("RGB")
    diff = ImageChops.difference(img, recomp)
    # Reduce to luminance — max across RGB channels per pixel.
    diff_l = diff.convert("L")

    extrema = diff_l.getextrema()  # (min, max) for single-band "L"
    max_diff = int(cast(float, extrema[1]))
    # Mean diff over the whole frame.
    hist = diff_l.histogram()
    total_pix = img.size[0] * img.size[1]
    mean_diff = sum(i * c for i, c in enumerate(hist)) / max(1, total_pix)

    # Tile the diff into a grid and report tiles above threshold.
    patches: list[dict[str, Any]] = []
    w, h = img.size
    grid = 16  # 16x16 cells over the image
    cell_w = max(1, w // grid)
    cell_h = max(1, h // grid)
    for gy in range(grid):
        for gx in range(grid):
            x0 = gx * cell_w
            y0 = gy * cell_h
            x1 = w if gx == grid - 1 else (gx + 1) * cell_w
            y1 = h if gy == grid - 1 else (gy + 1) * cell_h
            tile = diff_l.crop((x0, y0, x1, y1))
            t_ext = tile.getextrema()
            tile_max = int(cast(float, t_ext[1]))
            if tile_max < threshold:
                continue
            t_hist = tile.histogram()
            t_total = (x1 - x0) * (y1 - y0)
            tile_mean = sum(i * c for i, c in enumerate(t_hist)) / max(1, t_total)
            patches.append(
                {
                    "box": [x0, y0, x1, y1],
                    "max_diff": tile_max,
                    "mean_diff": round(tile_mean, 3),
                }
            )
    return {
        "quality": quality,
        "threshold": threshold,
        "max_diff": max_diff,
        "mean_diff": round(mean_diff, 3),
        "patches": patches,
    }


# ---------------------------------------------------------------
# Crop
# ---------------------------------------------------------------


@dataclasses.dataclass
class CropBox:
    x0: int
    y0: int
    x1: int
    y1: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x0, self.y0, self.x1, self.y1)


def crop_region(
    path: Path | str,
    *,
    box: tuple[int, int, int, int],
    out_dir: Path | str,
    return_b64: bool = False,
) -> dict[str, Any]:
    """Crop ``box`` (x0,y0,x1,y1) out of the image at ``path`` and
    write it under ``out_dir``. Returns a dict with the output
    path, its sha256, and dimensions.

    Pillow's crop tolerates boxes outside the image (it pads with
    zeros) — we explicitly clamp here so the model gets a clear
    error rather than a silently-padded crop. A model that asks
    for ``(0, 0, w*2, h*2)`` is reasoning about the wrong frame.
    """
    img = _open_safely(path)
    w, h = img.size
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise ValueError(f"box {box} out of bounds for image of size {w}x{h}")
    cropped = img.crop((x0, y0, x1, y1))

    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)
    src_name = Path(path).stem
    out_path = out_dir_p / f"{src_name}_crop_{x0}_{y0}_{x1}_{y1}.png"
    cropped.save(out_path, format="PNG")

    # Compute sha256 of the OUTPUT (the cropped artifact).
    import hashlib

    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()

    result: dict[str, Any] = {
        "out_path": str(out_path),
        "sha256": sha,
        "width": x1 - x0,
        "height": y1 - y0,
        "bytes": out_path.stat().st_size,
    }
    if return_b64:
        import base64

        result["image_b64"] = base64.b64encode(out_path.read_bytes()).decode("ascii")
    return result


# ---------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------


def histogram(path: Path | str, *, bins: int = 16) -> dict[str, Any]:
    """Per-channel histogram, bucketed into ``bins`` bins of 256/bins
    intensity-width each. Returns a JSON-safe dict so the model
    can reason about exposure / clipping / colour cast without us
    serialising 256-entry arrays per channel.

    Shape::

      {
        "bins": 16,
        "channels": ["R", "G", "B"],
        "data": {
          "R": [count_bucket_0, count_bucket_1, ...],
          "G": [...],
          "B": [...]
        },
        "total_pixels": int
      }
    """
    if bins < 2 or bins > 256 or 256 % bins != 0:
        raise ValueError("bins must be a divisor of 256 in [2, 256]")
    img = _open_safely(path).convert("RGB")
    raw = img.histogram()  # 768 entries: R[0..255], G[0..255], B[0..255]
    width = 256 // bins
    data: dict[str, list[int]] = {"R": [], "G": [], "B": []}
    for ch_idx, ch in enumerate(("R", "G", "B")):
        offset = ch_idx * 256
        for b in range(bins):
            start = offset + b * width
            data[ch].append(sum(raw[start : start + width]))
    return {
        "bins": bins,
        "channels": ["R", "G", "B"],
        "data": data,
        "total_pixels": img.size[0] * img.size[1],
    }


# ---------------------------------------------------------------
# Perceptual hash
# ---------------------------------------------------------------


_HASH_ALGOS: dict[str, Callable[..., Any]] = {
    "phash": imagehash.phash,
    "dhash": imagehash.dhash,
    "ahash": imagehash.average_hash,
    "whash": imagehash.whash,
}


def perceptual_hash(
    path: Path | str,
    *,
    algorithm: str = "phash",
    hash_size: int = 8,
) -> dict[str, Any]:
    """Compute a perceptual hash. Default is pHash with 8x8 grid
    (the imagehash library's default — 64-bit fingerprint).
    """
    if algorithm not in _HASH_ALGOS:
        raise ValueError(f"unknown algorithm {algorithm!r}; choose from {sorted(_HASH_ALGOS)}")
    fn = _HASH_ALGOS[algorithm]
    img = _open_safely(path)
    h = fn(img, hash_size=hash_size)
    return {
        "algorithm": algorithm,
        "hash_size": hash_size,
        "hex": str(h),
    }


def phash_distance(h1: str, h2: str) -> int:
    """Hamming distance between two pHash hex strings produced by
    :func:`perceptual_hash`. Smaller is more similar.

    Conventional reading:
      0           identical
      1..8        strong match (mild crop / resize / re-encode)
      8..16       similar (same subject, transformed)
      > 16        probably different scenes
    """
    a = imagehash.hex_to_hash(h1)
    b = imagehash.hex_to_hash(h2)
    return int(a - b)


# ---------------------------------------------------------------
# Metadata-strip check
# ---------------------------------------------------------------


def metadata_strip_check(
    orig: Path | str,
    suspect: Path | str,
) -> dict[str, Any]:
    """Compare EXIF presence between two images.

    Returns ``{"verdict": "stripped"|"intact"|"different",
    "missing_keys": [...], "present_keys": [...]}``.

    "different" means the suspect HAS EXIF but is missing keys
    the original had — partial strip / re-export. "stripped"
    means the suspect has NO EXIF and the original did.
    """
    orig_ex = extract_exif(orig)
    sus_ex = extract_exif(suspect)
    orig_keys = set(orig_ex.keys())
    sus_keys = set(sus_ex.keys())
    missing = sorted(orig_keys - sus_keys)
    if not orig_keys:
        # Original itself has no EXIF — can't conclude anything.
        verdict = "indeterminate"
    elif not sus_keys:
        verdict = "stripped"
    elif missing:
        verdict = "different"
    else:
        verdict = "intact"
    return {
        "verdict": verdict,
        "missing_keys": missing,
        "present_keys": sorted(sus_keys),
        "original_keys": sorted(orig_keys),
    }
