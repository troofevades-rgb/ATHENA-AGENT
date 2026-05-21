"""T4-06.2 — ocr tool + composable helper tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.ocr import tools as ocr_tools
from athena.ocr.contract import OCRBlock, OCRResult
from athena.ocr.tools import _run, ocr_recognize
from tests.ocr.conftest import StubOCRBackend


def _cfg(**overrides: Any) -> SimpleNamespace:
    base = dict(
        profile="default",
        ocr_enabled=True,
        ocr_backend_prefer="local",
        ocr_languages=["eng"],
        ocr_min_confidence=0,
        ocr_tesseract_cmd=None,
        media_backend_prefer="local",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------


def test_tool_registered_in_vision_toolset():
    import athena.tools  # noqa: F401 — trigger registration
    from athena.tools.registry import get_tool
    t = get_tool("ocr")
    assert t is not None
    assert t.toolset == "vision"


def test_tool_schema_has_load_bearing_args():
    import athena.tools  # noqa: F401
    from athena.tools.registry import get_tool
    t = get_tool("ocr")
    props = t.parameters["properties"]
    assert "path" in props
    assert "languages" in props
    assert "with_boxes" in props
    assert "min_confidence" in props
    assert t.parameters["required"] == ["path"]


# ---------------------------------------------------------------
# Gate + validation
# ---------------------------------------------------------------


def test_ocr_disabled_short_circuits(tmp_path: Path):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    out = json.loads(_run(
        path=str(img),
        _cfg=_cfg(ocr_enabled=False),
        _backend=StubOCRBackend(),
    ))
    assert out["available"] is False
    assert "ocr_enabled=False" in out["error"]


def test_missing_path_rejected():
    out = json.loads(_run(
        path=None,
        _cfg=_cfg(),
        _backend=StubOCRBackend(),
    ))
    assert out["available"] is False
    assert "path is required" in out["error"]


def test_missing_file_rejected(tmp_path: Path):
    out = json.loads(_run(
        path=str(tmp_path / "nope.png"),
        _cfg=_cfg(),
        _backend=StubOCRBackend(),
    ))
    assert out["available"] is False
    assert "file not found" in out["error"]


def test_unavailable_when_no_backend(tmp_path: Path, monkeypatch):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    monkeypatch.setattr(ocr_tools, "_resolve_backend", lambda cfg: None)
    out = json.loads(_run(
        path=str(img),
        _cfg=_cfg(),
    ))
    assert out["available"] is False
    assert "no OCR backend configured" in out["reason"]


# ---------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------


def test_recognize_returns_text_and_blocks(tmp_path: Path):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    out = json.loads(_run(
        path=str(img),
        _cfg=_cfg(),
        _backend=StubOCRBackend(),
    ))
    assert out["available"] is True
    assert out["text"] == "Hello world\nSecond line"
    assert len(out["blocks"]) == 2
    assert out["blocks"][0]["bbox"] == [10, 10, 100, 40]
    assert out["language"] == "eng"
    assert out["backend"] == "ocr_stub"


def test_with_boxes_false_omits_blocks(tmp_path: Path):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    out = json.loads(_run(
        path=str(img),
        with_boxes=False,
        _cfg=_cfg(),
        _backend=StubOCRBackend(),
    ))
    assert out["available"] is True
    assert "blocks" not in out
    assert out["text"] == "Hello world\nSecond line"


def test_languages_passed_through(tmp_path: Path):
    """The default languages from cfg flow through to the
    backend.recognize call when none is given on the tool
    call."""
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    backend = StubOCRBackend()
    _run(
        path=str(img),
        _cfg=_cfg(ocr_languages=["eng", "fra"]),
        _backend=backend,
    )
    assert backend.recognize_calls[0]["langs"] == ["eng", "fra"]


def test_languages_override_per_call(tmp_path: Path):
    """A per-call languages= arg wins over cfg.ocr_languages."""
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    backend = StubOCRBackend()
    _run(
        path=str(img),
        languages=["deu"],
        _cfg=_cfg(ocr_languages=["eng", "fra"]),
        _backend=backend,
    )
    assert backend.recognize_calls[0]["langs"] == ["deu"]


# ---------------------------------------------------------------
# Confidence filter
# ---------------------------------------------------------------


def test_confidence_filter_drops_low_confidence_blocks(tmp_path: Path):
    """min_confidence=80 drops the second block (conf 78) but
    keeps the first (conf 92)."""
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    backend = StubOCRBackend()  # default blocks: 92.0 + 78.0
    out = json.loads(_run(
        path=str(img),
        min_confidence=80,
        _cfg=_cfg(),
        _backend=backend,
    ))
    assert len(out["blocks"]) == 1
    assert out["blocks"][0]["text"] == "Hello world"
    # The joined text excludes the dropped block.
    assert out["text"] == "Hello world"


def test_confidence_filter_from_cfg(tmp_path: Path):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    out = json.loads(_run(
        path=str(img),
        _cfg=_cfg(ocr_min_confidence=80),
        _backend=StubOCRBackend(),
    ))
    assert len(out["blocks"]) == 1


def test_confidence_filter_zero_keeps_everything(tmp_path: Path):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    out = json.loads(_run(
        path=str(img),
        min_confidence=0,
        _cfg=_cfg(),
        _backend=StubOCRBackend(),
    ))
    assert len(out["blocks"]) == 2


# ---------------------------------------------------------------
# Backend exception → structured error
# ---------------------------------------------------------------


def test_backend_exception_surfaces_as_structured_error(tmp_path: Path):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    backend = StubOCRBackend(
        raise_on_recognize=RuntimeError("tesseract crashed"),
    )
    out = json.loads(_run(
        path=str(img),
        _cfg=_cfg(),
        _backend=backend,
    ))
    # ocr_recognize swallows backend exceptions + returns empty
    # OCRResult — so the tool succeeds with empty text rather
    # than surfacing the error. This matches the spec:
    # "engine failures → empty + WARNING log, never raise into
    # the tool layer".
    assert out["available"] is True
    assert out["text"] == ""
    assert out["blocks"] == []


# ---------------------------------------------------------------
# ocr_recognize composable helper
# ---------------------------------------------------------------


def test_ocr_recognize_returns_result_directly(tmp_path: Path):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    result = ocr_recognize(
        img, cfg=_cfg(), backend=StubOCRBackend(),
    )
    assert isinstance(result, OCRResult)
    assert len(result.blocks) == 2


def test_ocr_recognize_applies_min_confidence(tmp_path: Path):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    result = ocr_recognize(
        img, cfg=_cfg(), backend=StubOCRBackend(),
        min_confidence=80,
    )
    assert len(result.blocks) == 1
    assert result.blocks[0].confidence == 92.0


def test_ocr_recognize_no_backend_returns_empty(tmp_path: Path, monkeypatch):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    monkeypatch.setattr(ocr_tools, "_resolve_backend", lambda cfg: None)
    result = ocr_recognize(img, cfg=_cfg())
    assert result.blocks == []


def test_ocr_recognize_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        ocr_recognize(
            tmp_path / "nope.png",
            cfg=_cfg(),
            backend=StubOCRBackend(),
        )
