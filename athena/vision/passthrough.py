"""Provider-agnostic image passthrough (T4-01.4).

Turns a local file path into a content block that fits the
target provider's chat-API shape, with deterministic tiling
when the input exceeds the provider's max edge.

Why this exists: vision models don't all speak the same content-
block dialect. Anthropic wants ``{"type":"image","source":
{"type":"base64","media_type":...,"data":...}}``. OpenAI-shaped
APIs (and Ollama's OpenAI-compatible front door) want
``{"type":"image_url","image_url":{"url":"data:image/...;base64,..."}}``.
Ollama's native chat endpoint accepts a top-level ``images=``
list of base64 strings on each message — that path is plumbed
in T4-01.7.

Tiling policy:
  - We TILE, we do not DOWNSAMPLE. A downsample irreversibly
    loses information; tiling preserves it (the model gets the
    whole picture as N pieces).
  - Per provider, the policy uses these long-edge caps:
      anthropic : 1568 px
      openai    : 2048 px
      ollama    : 1344 px
    Sourced from each vendor's image input recommendation;
    documented in docs/reference/vision-analyze.md.
  - Tiles are produced as a 2x2 grid (or 2x1 / 1x2) until every
    tile's long edge is <= cap. Recursion is shallow in practice
    (a 6000px input tiles once).

Returns shape (typed-ish):

  passthrough_blocks(path, *, provider) -> {
      "provider": "anthropic" | "openai" | "ollama",
      "tiled":   True | False,
      "blocks":  [ {provider-shaped content block}, ... ]
  }

Each block also carries a tile coordinate label (e.g.
``"tile_0_0"``) in its own image metadata under
``image_url.detail`` (OpenAI) or as a separate sibling text
block for Anthropic / Ollama, so the model can reference tiles
unambiguously across multi-turn discussion.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from PIL import Image

Provider = Literal["anthropic", "openai", "ollama"]


# Long-edge caps (in pixels) above which we tile. Below these,
# the image goes through as a single block.
LONG_EDGE_CAP: dict[Provider, int] = {
    "anthropic": 1568,
    "openai": 2048,
    "ollama": 1344,
}


# Per-provider MIME defaults. We always re-encode tiles as PNG
# (lossless) since the original format may not be the right
# carrier for a cropped sub-region. Single-block passthrough
# preserves the original format when possible.
_DEFAULT_MIME = "image/png"
_FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}


@dataclass
class TileLabel:
    """Coordinate label for a tile in a grid. (0,0) is top-left."""

    row: int
    col: int

    def as_str(self) -> str:
        return f"tile_{self.row}_{self.col}"


def _image_format(img: Image.Image) -> str:
    return (img.format or "PNG").upper()


def _bytes_for_provider(
    img: Image.Image,
    *,
    prefer_original_format: bool = False,
) -> tuple[bytes, str]:
    """Encode an image to bytes + MIME.

    If ``prefer_original_format`` and the format is supported,
    we keep it (saves bandwidth on a JPEG-in, JPEG-out path).
    Otherwise we emit PNG (lossless) for tiles / cropped regions.
    """
    fmt = _image_format(img)
    if prefer_original_format and fmt in _FORMAT_TO_MIME:
        out = fmt
        mime = _FORMAT_TO_MIME[fmt]
    else:
        out = "PNG"
        mime = _DEFAULT_MIME
    buf = io.BytesIO()
    save_kwargs: dict[str, Any] = {}
    if out == "JPEG":
        # quality=90 keeps detail without ballooning the payload.
        save_kwargs["quality"] = 90
    img.save(buf, format=out, **save_kwargs)
    return buf.getvalue(), mime


def _image_block(
    img: Image.Image,
    *,
    provider: Provider,
    label: str | None = None,
    prefer_original_format: bool = False,
) -> dict[str, Any]:
    """Produce one provider-shaped content block for an in-memory image."""
    data, mime = _bytes_for_provider(img, prefer_original_format=prefer_original_format)
    b64 = base64.b64encode(data).decode("ascii")
    if provider == "anthropic":
        block: dict[str, Any] = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime,
                "data": b64,
            },
        }
        if label:
            block["__tile_label__"] = label
        return block
    if provider == "openai":
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{b64}",
                # `detail` is OpenAI-specific; "high" is the
                # full-fidelity mode. We piggyback the tile
                # label here so multi-turn discussion has a
                # stable handle.
                "detail": label or "high",
            },
        }
    # ollama — native chat shape uses top-level `images=` on the
    # message itself; here we return a sentinel dict the caller
    # (T4-01.7 ollama provider) will unwrap. Mirrors the OpenAI
    # data-URL when called via Ollama's OpenAI-compatible front
    # door.
    return {
        "type": "image",
        "media_type": mime,
        "data": b64,
        "label": label or "image",
    }


def _tile_2d(img: Image.Image, cap: int) -> list[tuple[TileLabel, Image.Image]]:
    """Tile ``img`` recursively until every tile's long edge <= cap.

    Returns a flat list of (label, sub-image) pairs in row-major
    order. A near-square image tiles 2x2; a tall image tiles 1xN
    or 2xN depending on the aspect ratio.
    """
    w, h = img.size
    if max(w, h) <= cap:
        return [(TileLabel(0, 0), img)]

    # Decide grid dimensions: split each axis if it exceeds cap.
    cols = 2 if w > cap else 1
    rows = 2 if h > cap else 1
    tile_w = w // cols
    tile_h = h // rows

    out: list[tuple[TileLabel, Image.Image]] = []
    for r in range(rows):
        for c in range(cols):
            x0 = c * tile_w
            y0 = r * tile_h
            x1 = w if c == cols - 1 else (c + 1) * tile_w
            y1 = h if r == rows - 1 else (r + 1) * tile_h
            sub = img.crop((x0, y0, x1, y1))
            # Recurse: still too big? Re-tile.
            if max(sub.size) > cap:
                # Re-label with parent coordinates first, then
                # flatten the child labels — labels chain like
                # "tile_0_0_tile_0_1" so multi-level tilings
                # are still unambiguous.
                child_tiles = _tile_2d(sub, cap)
                for child_label, child_img in child_tiles:
                    flat = TileLabel(r, c)
                    chained = f"{flat.as_str()}_{child_label.as_str()}"
                    out.append((TileLabel(r, c), child_img))
                    # Store the chained label on the image so
                    # the caller can pull it.
                    child_img.info["_chained_label"] = chained
            else:
                out.append((TileLabel(r, c), sub))
    return out


def passthrough_blocks(
    path: Path | str,
    *,
    provider: Provider,
    long_edge_cap: int | None = None,
) -> dict[str, Any]:
    """Return provider-shaped image content blocks for ``path``,
    tiled if the input exceeds the per-provider long-edge cap.

    Single-image passes (input fits the cap) return one block,
    encoded in the input's original format when supported (JPEG
    stays JPEG, PNG stays PNG). Tiled passes always emit PNG —
    a crop's original-format identity is meaningless.
    """
    if provider not in LONG_EDGE_CAP:
        raise ValueError(f"unknown provider {provider!r}; choose from {sorted(LONG_EDGE_CAP)}")
    cap = long_edge_cap or LONG_EDGE_CAP[provider]

    img: Image.Image = Image.open(Path(path))
    img.load()
    w, h = img.size

    if max(w, h) <= cap:
        block = _image_block(
            img,
            provider=provider,
            prefer_original_format=True,
        )
        return {"provider": provider, "tiled": False, "blocks": [block]}

    # Convert to RGB to normalise mode before tiling — some
    # palettised PNGs crop into weird modes otherwise.
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    tiles = _tile_2d(img, cap)
    blocks = []
    for label, sub in tiles:
        chained = sub.info.get("_chained_label", label.as_str())
        blocks.append(_image_block(sub, provider=provider, label=chained))
    return {"provider": provider, "tiled": True, "blocks": blocks}
