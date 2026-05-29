"""T4-05.1 — PDF extractor tests."""

from __future__ import annotations

from pathlib import Path

import pytest

# PyMuPDF (``fitz``) is an optional dependency -- the extractor and
# its test fixture both call into it. When the binary wheel isn't
# installed (e.g., CI's slim test image), skip the suite cleanly
# rather than letting the imports below blow up at collection time.
pytest.importorskip("fitz")

from athena.document.extractors.pdf import (  # noqa: E402
    extract,
    rasterize_page,
)
from athena.document.result import DocumentResult, OutlineEntry
from tests.document.conftest import (
    make_pdf_with_outline,
    make_pdf_with_scanned_page,
    make_pdf_with_text,
)


def test_pdf_text_extraction(tmp_path: Path):
    """Text comes back in reading order across pages, joined
    by form-feed."""
    pdf = make_pdf_with_text(tmp_path / "a.pdf")
    result = extract(pdf)
    assert isinstance(result, DocumentResult)
    assert result.pages == 2
    # Both pages' content present in reading order.
    assert "First page heading" in result.text
    assert "Second page heading" in result.text
    # Form-feed separator between pages.
    assert "\f" in result.text
    first, second = result.text.split("\f")
    assert "First page" in first and "Second page" in second
    # No pages flagged as scanned (text layer present on both).
    assert result.scanned_pages == []


def test_pdf_metadata_extraction(tmp_path: Path):
    pdf = make_pdf_with_text(
        tmp_path / "a.pdf",
        title="Specific Title",
        author="A. Specific Author",
    )
    result = extract(pdf)
    assert result.metadata["title"] == "Specific Title"
    assert result.metadata["author"] == "A. Specific Author"
    assert result.metadata["format"] == "PDF"
    assert result.metadata["page_count"] == 2


def test_pdf_outline_extraction(tmp_path: Path):
    """Document outline (table of contents) comes through with
    correct levels + pages."""
    pdf = make_pdf_with_outline(tmp_path / "outlined.pdf")
    result = extract(pdf)
    assert len(result.outline) == 5
    titles = [e.title for e in result.outline]
    assert titles == [
        "Introduction",
        "Methods",
        "Sub-method A",
        "Results",
        "Conclusion",
    ]
    # Levels preserved.
    levels = [e.level for e in result.outline]
    assert levels == [1, 1, 2, 1, 1]
    # Pages 1-indexed.
    pages = [e.page for e in result.outline]
    assert pages == [1, 2, 2, 3, 4]
    # OutlineEntry shape.
    assert isinstance(result.outline[0], OutlineEntry)


def test_pdf_per_page_text_indexed(tmp_path: Path):
    """page_texts dict carries 1-indexed per-page text so the
    tool layer can splice in OCR for scanned pages."""
    pdf = make_pdf_with_text(tmp_path / "a.pdf")
    result = extract(pdf)
    assert set(result.page_texts.keys()) == {1, 2}
    assert "First page" in result.page_texts[1]
    assert "Second page" in result.page_texts[2]


def test_pdf_scanned_pages_flagged(tmp_path: Path):
    """A page with no text layer is flagged in scanned_pages —
    the signal the OCR-fallback tool layer keys off."""
    pdf = make_pdf_with_scanned_page(tmp_path / "scanned.pdf")
    result = extract(pdf)
    assert result.pages == 2
    # Page 1 has text; page 2 is blank → flagged scanned.
    assert result.scanned_pages == [2]
    # ocr_pages still empty until the tool layer does OCR.
    assert result.ocr_pages == []


def test_pdf_rasterize_page_returns_png_bytes(tmp_path: Path):
    pdf = make_pdf_with_text(tmp_path / "a.pdf")
    png = rasterize_page(pdf, page=1, dpi=150)
    assert isinstance(png, bytes)
    # PNG magic prefix.
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    # Non-trivial size.
    assert len(png) > 100


def test_pdf_rasterize_page_out_of_range_raises(tmp_path: Path):
    pdf = make_pdf_with_text(tmp_path / "a.pdf")
    with pytest.raises(ValueError, match="out of range"):
        rasterize_page(pdf, page=99)


def test_pdf_normalized_shape(tmp_path: Path):
    """The .normalized() output is JSON-safe + has the expected
    top-level keys."""
    import json

    pdf = make_pdf_with_text(tmp_path / "a.pdf")
    nd = extract(pdf).normalized()
    # Must round-trip through JSON without error.
    json.dumps(nd)
    assert set(nd.keys()) >= {
        "text",
        "pages",
        "outline",
        "tables",
        "metadata",
        "scanned_pages",
        "ocr_pages",
        "figures",
    }
