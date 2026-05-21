"""T4-06.1 — OCR backend + capability + contract tests.

Pure-Python — no tesseract binary required (the stub backend
covers protocol behavior; the live adapter is exercised
end-to-end in the smoke step, gated on tesseract being
installed).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.ocr.contract import OCRBlock, OCRResult


# ---------------------------------------------------------------
# Capability + manifest declaration
# ---------------------------------------------------------------


def test_capabilities_has_ocr_field():
    from athena.providers.base import Capabilities
    c = Capabilities()
    assert hasattr(c, "ocr")
    assert c.ocr is False  # safe default


def test_capabilities_supports_ocr_lookup():
    from athena.providers.base import Capabilities
    assert Capabilities(ocr=True).supports("ocr") is True
    assert Capabilities().supports("ocr") is False


def test_tesseract_backend_declares_capability():
    """Importing athena.ocr.backends registers the adapter +
    its static_capabilities() declares ocr=True + is_local=True
    + NOT a chat backend."""
    from athena.ocr import backends  # noqa: F401 — trigger
    from athena.ocr.backends.tesseract_local import (
        TesseractLocalBackend,
    )
    caps = TesseractLocalBackend.static_capabilities()
    assert caps.ocr is True
    assert caps.is_local is True
    assert caps.tool_calls is False
    assert caps.streaming is False


# ---------------------------------------------------------------
# Broker resolution
# ---------------------------------------------------------------


def test_media_registry_resolves_ocr_to_local():
    from athena.ocr import backends  # noqa: F401 — register
    from athena.ocr.backends.tesseract_local import (
        TesseractLocalBackend,
    )
    from athena.media.registry import MediaRegistry

    cfg = SimpleNamespace(media_backend_prefer="local")
    cls = MediaRegistry(cfg=cfg).backend_for("ocr")
    assert cls is TesseractLocalBackend


def test_media_registry_can_ocr():
    from athena.ocr import backends  # noqa: F401
    from athena.media.registry import MediaRegistry

    cfg = SimpleNamespace(media_backend_prefer="local")
    assert MediaRegistry(cfg=cfg).can("ocr") is True


# ---------------------------------------------------------------
# OCRBlock + OCRResult
# ---------------------------------------------------------------


def test_ocrblock_to_dict_shape():
    b = OCRBlock(text="hello", bbox=(1, 2, 30, 40), confidence=87.345)
    d = b.to_dict()
    assert d == {"text": "hello", "bbox": [1, 2, 30, 40], "confidence": 87.3}


def test_ocrresult_to_dict_with_boxes():
    r = OCRResult(
        blocks=[
            OCRBlock(text="line one", bbox=(0, 0, 10, 10), confidence=90.0),
            OCRBlock(text="line two", bbox=(0, 12, 10, 22), confidence=85.0),
        ],
        language="eng",
    )
    d = r.to_dict(with_boxes=True)
    assert d["text"] == "line one\nline two"
    assert d["language"] == "eng"
    assert len(d["blocks"]) == 2


def test_ocrresult_to_dict_without_boxes_omits_blocks():
    r = OCRResult(
        blocks=[
            OCRBlock(text="a", bbox=(0, 0, 1, 1), confidence=99.0),
        ],
    )
    d = r.to_dict(with_boxes=False)
    assert "blocks" not in d
    assert d["text"] == "a"


def test_ocrresult_joined_text_skips_empty_blocks():
    r = OCRResult(blocks=[
        OCRBlock(text="hello", bbox=(0, 0, 1, 1), confidence=90.0),
        OCRBlock(text="", bbox=(0, 0, 1, 1), confidence=20.0),
        OCRBlock(text="world", bbox=(0, 0, 1, 1), confidence=90.0),
    ])
    assert r.joined_text() == "hello\nworld"


def test_ocrresult_empty_no_blocks():
    r = OCRResult(blocks=[])
    d = r.to_dict()
    assert d == {"text": "", "blocks": []}


# ---------------------------------------------------------------
# Stub backend protocol contract
# ---------------------------------------------------------------


def test_stub_returns_default_blocks(stub_ocr, tmp_path: Path):
    img = tmp_path / "x.png"
    img.write_bytes(b"")
    result = stub_ocr.recognize(img)
    assert len(result.blocks) == 2
    assert result.blocks[0].text == "Hello world"
    assert result.language == "eng"
    # Recorded the call
    assert len(stub_ocr.recognize_calls) == 1
    assert stub_ocr.recognize_calls[0]["with_boxes"] is True


def test_stub_passes_languages_through(stub_ocr, tmp_path: Path):
    img = tmp_path / "x.png"
    img.write_bytes(b"")
    stub_ocr.recognize(img, langs=["eng", "fra"])
    assert stub_ocr.recognize_calls[0]["langs"] == ["eng", "fra"]


def test_stub_unavailable_path(stub_ocr):
    stub_ocr._available = False
    assert stub_ocr.is_available() is False


# ---------------------------------------------------------------
# Tesseract backend lightweight checks (no binary call)
# ---------------------------------------------------------------


def test_tesseract_backend_is_available_returns_bool():
    """The live backend's is_available depends on whether
    tesseract is installed on this host. We don't require it
    for tests — just confirm the call shape returns a bool
    (False is fine; the rest of the suite uses the stub)."""
    from athena.ocr.backends.tesseract_local import TesseractLocalBackend
    avail = TesseractLocalBackend().is_available()
    assert isinstance(avail, bool)


def test_tesseract_backend_chat_methods_raise():
    """Capability-only provider — chat methods must error,
    not silently no-op."""
    from athena.ocr.backends.tesseract_local import TesseractLocalBackend
    b = TesseractLocalBackend()
    with pytest.raises(NotImplementedError):
        b.stream_chat(model="x", messages=[])
    # parse_tool_calls is permissive — matches sibling capability-
    # only backends.
    out, calls = b.parse_tool_calls("text", {})
    assert out == "text"
    assert calls == []


def test_coalesce_blocks_groups_per_word_rows():
    """Pin the pytesseract row-shape coalescing logic so a
    refactor of _coalesce_blocks doesn't silently change the
    block boundaries the model sees."""
    from athena.ocr.backends.tesseract_local import _coalesce_blocks

    # Simulated pytesseract image_to_data output: two blocks
    # ("hello world" + "second line"), each with multi-word
    # rows at level 5.
    data = {
        "level":     [1, 2, 5, 5, 2, 5, 5],
        "page_num":  [1, 1, 1, 1, 1, 1, 1],
        "block_num": [0, 1, 1, 1, 2, 2, 2],
        "par_num":   [0, 0, 0, 0, 0, 0, 0],
        "text":      ["", "", "hello", "world", "", "second", "line"],
        "conf":      [-1, -1, 90, 92, -1, 80, 75],
        "left":      [0, 0, 10, 60, 0, 10, 80],
        "top":       [0, 0, 10, 10, 0, 50, 50],
        "width":     [0, 0, 40, 40, 0, 60, 30],
        "height":    [0, 0, 20, 20, 0, 20, 20],
    }
    blocks = _coalesce_blocks(data)
    assert len(blocks) == 2
    assert blocks[0].text == "hello world"
    assert blocks[1].text == "second line"
    # bbox covers both words.
    assert blocks[0].bbox == (10, 10, 100, 30)
    # Confidence averaged.
    assert blocks[0].confidence == pytest.approx(91.0, abs=0.1)


def test_coalesce_blocks_skips_negative_confidence_rows():
    """Rows with conf=-1 (tesseract's 'no confidence' marker)
    are skipped so they don't drag the average down."""
    from athena.ocr.backends.tesseract_local import _coalesce_blocks

    data = {
        "level":     [5, 5, 5],
        "page_num":  [1, 1, 1],
        "block_num": [1, 1, 1],
        "par_num":   [0, 0, 0],
        "text":      ["good", "junk", "more"],
        "conf":      [95, -1, 90],
        "left":      [0, 0, 0],
        "top":       [0, 0, 0],
        "width":     [10, 10, 10],
        "height":    [10, 10, 10],
    }
    blocks = _coalesce_blocks(data)
    assert blocks[0].text == "good more"  # junk dropped
    assert blocks[0].confidence == pytest.approx(92.5)
