"""Normalized result type every extractor produces (T4-05.1).

The same shape across PDF / DOCX / future formats so the tool
layer's JSON output is stable regardless of which adapter ran.
"""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class OutlineEntry:
    """One entry in the document's heading outline."""

    level: int       # 1 = top-level heading, 2 = sub, ...
    title: str
    page: int        # 1-indexed page where the heading starts;
                     # 0 for formats without page-level positioning

    def to_dict(self) -> dict[str, Any]:
        return {"level": int(self.level), "title": self.title, "page": int(self.page)}


@dataclasses.dataclass(frozen=True)
class TableData:
    """One extracted table — rows of cells. Each row is a list
    of strings; ragged tables (rows with different cell counts)
    are passed through as-is rather than normalised to a
    rectangle, since the underlying document IS ragged in that
    case and pretending otherwise would silently drop data."""

    page: int               # 1-indexed; 0 for DOCX (no pages)
    rows: list[list[str]]   # row-major

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": int(self.page),
            "rows": [list(r) for r in self.rows],
            "row_count": len(self.rows),
            "col_count": max((len(r) for r in self.rows), default=0),
        }


@dataclasses.dataclass(frozen=True)
class FigureRef:
    """One embedded figure / image reference.

    `page` is 1-indexed (PDF) or 0 (DOCX). `bbox` is the bounding
    box in page coordinates (x0, y0, x1, y1) when known; None
    when the format doesn't expose it.

    `description` is filled in by the tool layer when
    `extract=full` AND vision is available. Extractors leave it
    None.
    """

    page: int
    bbox: tuple[float, float, float, float] | None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"page": int(self.page)}
        if self.bbox is not None:
            d["bbox"] = list(self.bbox)
        if self.description is not None:
            d["description"] = self.description
        return d


@dataclasses.dataclass
class DocumentResult:
    """Normalized output across every extractor.

    ``text`` is the full document's reading-order text. For PDFs,
    pages are joined with a form-feed (``\\f``) so a downstream
    consumer can re-split per page. For DOCX, the body text is
    one continuous string (no page breaks at extraction time).

    ``pages`` is the total page count for paginated formats; 0
    when not applicable (DOCX).

    ``scanned_pages`` lists 1-indexed pages where no text layer
    was found (PDF only). The tool layer routes these to OCR
    (T4-06) when available and merges the OCR text back into
    ``text``; pages that round-trip via OCR also appear in
    ``ocr_pages``.

    ``ocr_pages`` is the subset of ``scanned_pages`` that
    actually got OCR'd. Empty until the tool layer fills it in.

    ``figures`` is filled by the extractors at discovery time
    (just refs + bboxes). The tool layer fills in `.description`
    via vision_analyze when `extract=full` and vision is
    available.
    """

    text: str
    pages: int
    outline: list[OutlineEntry] = dataclasses.field(default_factory=list)
    tables: list[TableData] = dataclasses.field(default_factory=list)
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)
    scanned_pages: list[int] = dataclasses.field(default_factory=list)
    ocr_pages: list[int] = dataclasses.field(default_factory=list)
    figures: list[FigureRef] = dataclasses.field(default_factory=list)
    # Per-page text indexed by 1-based page number — the tool
    # layer uses this to splice in OCR text for scanned pages
    # without re-parsing the whole document.
    page_texts: dict[int, str] = dataclasses.field(default_factory=dict)

    def normalized(self) -> dict[str, Any]:
        """JSON-safe dict shape the tool returns to the model.
        Stable across formats."""
        return {
            "text": self.text,
            "pages": int(self.pages),
            "outline": [o.to_dict() for o in self.outline],
            "tables": [t.to_dict() for t in self.tables],
            "metadata": dict(self.metadata),
            "scanned_pages": list(self.scanned_pages),
            "ocr_pages": list(self.ocr_pages),
            "figures": [f.to_dict() for f in self.figures],
        }
