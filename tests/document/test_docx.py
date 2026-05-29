"""T4-05.1 — DOCX extractor tests."""

from __future__ import annotations

from pathlib import Path

import pytest

# python-docx is an optional dependency. Same reasoning as
# tests/document/test_pdf.py: skip cleanly when the package isn't
# installed rather than letting the extractor or fixture imports
# raise at collection time.
pytest.importorskip("docx")

from athena.document.extractors.docx import extract  # noqa: E402
from athena.document.result import DocumentResult  # noqa: E402
from tests.document.conftest import make_docx_with_structure  # noqa: E402


def test_docx_structure(tmp_path: Path):
    """DOCX with Title + Heading-N styles + body paragraphs +
    a table produces a DocumentResult with the right outline +
    table + text."""
    doc = make_docx_with_structure(tmp_path / "structured.docx")
    result = extract(doc)
    assert isinstance(result, DocumentResult)
    # DOCX has no pages concept at parse time.
    assert result.pages == 0
    # No scanned pages either.
    assert result.scanned_pages == []
    # Body text contains every heading + paragraph.
    assert "Test DOCX" in result.text
    assert "Section A" in result.text
    assert "Sub-section A1" in result.text
    assert "Section B" in result.text
    assert "Paragraph one in section A." in result.text


def test_docx_outline_extraction(tmp_path: Path):
    """Title → level 1; Heading 1 → level 1; Heading 2 → level 2."""
    doc = make_docx_with_structure(tmp_path / "structured.docx")
    result = extract(doc)
    titles = [e.title for e in result.outline]
    levels = [e.level for e in result.outline]
    # Title comes first at level 1, then Section A (level 1),
    # then Sub-section A1 (level 2), then Section B (level 1).
    assert "Test DOCX" in titles
    assert "Section A" in titles
    assert "Sub-section A1" in titles
    assert "Section B" in titles
    # All Heading entries land at sane levels (1 or 2).
    assert all(level in (1, 2) for level in levels)
    # Sub-section is one level deeper than Section.
    idx_section = titles.index("Section A")
    idx_sub = titles.index("Sub-section A1")
    assert levels[idx_section] == 1
    assert levels[idx_sub] == 2


def test_docx_table_extraction(tmp_path: Path):
    doc = make_docx_with_structure(tmp_path / "structured.docx")
    result = extract(doc)
    assert len(result.tables) == 1
    tbl = result.tables[0]
    assert tbl.page == 0  # DOCX has no page concept
    assert len(tbl.rows) == 2  # header + 1 data row
    assert tbl.rows[0] == ["Name", "Age", "Role"]
    assert tbl.rows[1] == ["Alice", "30", "Engineer"]


def test_docx_metadata_extraction(tmp_path: Path):
    doc = make_docx_with_structure(tmp_path / "structured.docx")
    result = extract(doc)
    assert result.metadata["title"] == "Test DOCX"
    assert result.metadata["author"] == "athena"
    assert result.metadata["format"] == "DOCX"


def test_docx_normalized_shape(tmp_path: Path):
    """Same JSON-safe shape as the PDF extractor."""
    import json

    doc = make_docx_with_structure(tmp_path / "structured.docx")
    nd = extract(doc).normalized()
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
