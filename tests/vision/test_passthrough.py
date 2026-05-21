"""T4-01.4 — passthrough + tiling tests.

Pins:

  - Single-image pass: input <= cap → exactly one block in the
    provider's shape, untouched encoding when possible.
  - Tiled pass: input > cap → multiple blocks, each tile's
    long edge <= cap.
  - Per-provider block shapes (Anthropic source/base64, OpenAI
    image_url+data URI, Ollama sentinel dict).
  - Long-edge caps follow the documented per-provider values.
  - Unknown provider rejected.
  - All blocks carry decodable base64 → round-trip through
    Pillow without crashing.
"""

from __future__ import annotations

import base64
import io
import re

import pytest
from PIL import Image

from athena.vision.passthrough import (
    LONG_EDGE_CAP,
    passthrough_blocks,
)
from tests.vision.fixtures import FIXTURES_DIR, ensure_fixtures


# ---------------------------------------------------------------
# happy paths per provider
# ---------------------------------------------------------------


def test_small_image_returns_single_block_anthropic():
    ensure_fixtures()
    out = passthrough_blocks(FIXTURES_DIR / "small.png", provider="anthropic")
    assert out["provider"] == "anthropic"
    assert out["tiled"] is False
    assert len(out["blocks"]) == 1
    b = out["blocks"][0]
    assert b["type"] == "image"
    assert b["source"]["type"] == "base64"
    assert b["source"]["media_type"].startswith("image/")
    # base64 round-trips through Pillow
    payload = base64.b64decode(b["source"]["data"])
    Image.open(io.BytesIO(payload)).verify()


def test_small_image_returns_single_block_openai():
    ensure_fixtures()
    out = passthrough_blocks(FIXTURES_DIR / "small.png", provider="openai")
    assert out["tiled"] is False
    b = out["blocks"][0]
    assert b["type"] == "image_url"
    url = b["image_url"]["url"]
    assert url.startswith("data:image/")
    # Round-trip the payload after the comma.
    mime_part, b64_part = url.split(",", 1)
    payload = base64.b64decode(b64_part)
    Image.open(io.BytesIO(payload)).verify()


def test_small_image_returns_single_block_ollama():
    ensure_fixtures()
    out = passthrough_blocks(FIXTURES_DIR / "small.png", provider="ollama")
    assert out["tiled"] is False
    b = out["blocks"][0]
    assert b["type"] == "image"
    assert "data" in b
    payload = base64.b64decode(b["data"])
    Image.open(io.BytesIO(payload)).verify()


# ---------------------------------------------------------------
# tiling
# ---------------------------------------------------------------


def test_large_image_tiles_for_ollama():
    """large.png is 2400x1200; Ollama cap is 1344 → must tile."""
    ensure_fixtures()
    out = passthrough_blocks(FIXTURES_DIR / "large.png", provider="ollama")
    assert out["tiled"] is True
    assert len(out["blocks"]) > 1


def test_tile_long_edge_under_cap_for_ollama():
    ensure_fixtures()
    out = passthrough_blocks(FIXTURES_DIR / "large.png", provider="ollama")
    cap = LONG_EDGE_CAP["ollama"]
    for b in out["blocks"]:
        payload = base64.b64decode(b["data"])
        img = Image.open(io.BytesIO(payload))
        assert max(img.size) <= cap, f"tile {img.size} exceeds cap {cap}"


def test_tile_long_edge_under_cap_for_anthropic():
    """large.png is 2400px; Anthropic cap 1568 → tiles."""
    ensure_fixtures()
    out = passthrough_blocks(FIXTURES_DIR / "large.png", provider="anthropic")
    assert out["tiled"] is True
    cap = LONG_EDGE_CAP["anthropic"]
    for b in out["blocks"]:
        payload = base64.b64decode(b["source"]["data"])
        img = Image.open(io.BytesIO(payload))
        assert max(img.size) <= cap


def test_no_tile_when_under_openai_cap():
    """large.png is 2400x1200; OpenAI cap is 2048 → tiles (long
    edge 2400 > 2048). Use a smaller fixture to test no-tile."""
    ensure_fixtures()
    out = passthrough_blocks(FIXTURES_DIR / "original.jpg", provider="openai")
    # original.jpg is 800x600 → well under any cap.
    assert out["tiled"] is False
    assert len(out["blocks"]) == 1


def test_tiles_carry_distinct_labels():
    """Each tile in a tiled pass must carry a distinct
    coordinate label so the model can reference them."""
    ensure_fixtures()
    out = passthrough_blocks(FIXTURES_DIR / "large.png", provider="openai")
    labels = [b["image_url"]["detail"] for b in out["blocks"]]
    assert len(set(labels)) == len(labels)
    # Labels look like "tile_R_C..."
    for lab in labels:
        assert re.match(r"tile_\d+_\d+", lab)


# ---------------------------------------------------------------
# negative paths
# ---------------------------------------------------------------


def test_unknown_provider_rejected():
    ensure_fixtures()
    with pytest.raises(ValueError, match="unknown provider"):
        passthrough_blocks(FIXTURES_DIR / "small.png", provider="bogus")  # type: ignore[arg-type]


def test_custom_cap_forces_tile_on_small_image():
    """A custom cap below the input dimensions forces tiling
    even on a small fixture — used to test the tile path under
    isolation without needing a >2000px asset."""
    ensure_fixtures()
    # small.png is 320x240; force cap=200
    out = passthrough_blocks(
        FIXTURES_DIR / "small.png",
        provider="anthropic",
        long_edge_cap=200,
    )
    assert out["tiled"] is True
    assert len(out["blocks"]) >= 2
