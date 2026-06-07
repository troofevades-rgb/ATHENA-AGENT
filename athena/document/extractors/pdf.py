"""PDF extractor via PyMuPDF (T4-05.1).

PyMuPDF (the ``fitz`` import) is the right choice for athena:
fast C-backed, good text-in-reading-order extraction, has a
native table finder, can rasterize pages to images (the OCR
fallback in the tool layer needs this), and reads the document
outline (table of contents) directly.

Library isolation: every PyMuPDF API call lives in this one
file. A future swap to pypdf / pdfplumber would only touch
this module.

Per-page text-layer detection: a page that returns less than
``_TEXT_LAYER_MIN_CHARS`` after whitespace strip is flagged as
"scanned" — the tool layer hands those pages to OCR (T4-06) +
merges the result back in.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

from ..result import (
    DocumentResult,
    FigureRef,
    OutlineEntry,
    TableData,
)

logger = logging.getLogger(__name__)


# A page with fewer characters than this after strip is treated
# as having no text layer (image-only / scanned page). The
# threshold is conservative — even a sparse text-layer page
# (one paragraph) clears it.
_TEXT_LAYER_MIN_CHARS = 20


def extract(path: Path | str) -> DocumentResult:
    """Parse a PDF into a normalized DocumentResult.

    Stream-friendly: reads one page at a time, joins page text
    with form-feed (``\\f``) so downstream consumers can re-
    split per page. Outline + tables + metadata + figures all
    pulled from PyMuPDF native APIs.
    """
    import fitz  # PyMuPDF; lazy so unused → no import cost

    p = Path(path)
    doc = fitz.open(str(p))
    try:
        page_texts: dict[int, str] = {}
        scanned: list[int] = []
        full_text_parts: list[str] = []

        for page_idx in range(doc.page_count):
            page = doc.load_page(page_idx)
            page_no = page_idx + 1
            text = page.get_text("text") or ""
            page_texts[page_no] = text
            full_text_parts.append(text)
            if len(text.strip()) < _TEXT_LAYER_MIN_CHARS:
                scanned.append(page_no)

        # Form-feed between pages — the conventional reader's
        # page-separator. Downstream `text.split("\\f")` recovers
        # the per-page slices.
        full_text = "\f".join(full_text_parts)

        outline = _extract_outline(doc)
        tables = _extract_tables(doc)
        figures = _extract_figures(doc)
        metadata = _extract_metadata(doc)

        return DocumentResult(
            text=full_text,
            pages=doc.page_count,
            outline=outline,
            tables=tables,
            metadata=metadata,
            scanned_pages=scanned,
            figures=figures,
            page_texts=page_texts,
        )
    finally:
        doc.close()


def rasterize_page(
    path: Path | str,
    page: int,
    *,
    dpi: int = 200,
) -> bytes:
    """Render a 1-indexed PDF page to PNG bytes for OCR.

    The mono / no-alpha colorspace + the configurable DPI match
    what tesseract-class engines want. 200 DPI is the OCR
    sweet spot; bump to 300 for fine print, drop to 150 for
    speed on big batches."""
    import fitz

    doc = fitz.open(str(path))
    try:
        if page < 1 or page > doc.page_count:
            raise ValueError(f"page {page} out of range (1..{doc.page_count})")
        p = doc.load_page(page - 1)
        # alpha=False keeps the PNG mono-channel-suitable;
        # the matrix scales the 72-DPI base to the requested DPI.
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = p.get_pixmap(matrix=matrix, alpha=False)
        return cast(bytes, pix.tobytes("png"))
    finally:
        doc.close()


# ---------------------------------------------------------------
# internals
# ---------------------------------------------------------------


def _extract_outline(doc: Any) -> list[OutlineEntry]:
    """PyMuPDF's get_toc() returns ``[[level, title, page], ...]``
    in document order. Map to our OutlineEntry directly."""
    try:
        toc = doc.get_toc(simple=True) or []
    except Exception:  # noqa: BLE001
        logger.debug("PDF outline extraction failed", exc_info=True)
        return []
    out: list[OutlineEntry] = []
    for entry in toc:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        try:
            out.append(
                OutlineEntry(
                    level=int(entry[0]),
                    title=str(entry[1]).strip(),
                    page=int(entry[2]),
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def _extract_tables(doc: Any) -> list[TableData]:
    """PyMuPDF (>=1.23) has a native ``find_tables()`` method.
    Older versions don't — we fall back to an empty list so
    extraction never raises into the caller."""
    tables: list[TableData] = []
    for page_idx in range(doc.page_count):
        page = doc.load_page(page_idx)
        if not hasattr(page, "find_tables"):
            continue
        try:
            finder = page.find_tables()
        except Exception:  # noqa: BLE001
            logger.debug(
                "PDF table extraction failed on page %d",
                page_idx + 1,
                exc_info=True,
            )
            continue
        for tbl in finder.tables if hasattr(finder, "tables") else []:
            try:
                rows = tbl.extract() or []
            except Exception:  # noqa: BLE001
                continue
            normalised_rows: list[list[str]] = []
            for r in rows:
                if not isinstance(r, (list, tuple)):
                    continue
                normalised_rows.append(["" if c is None else str(c) for c in r])
            if normalised_rows:
                tables.append(
                    TableData(
                        page=page_idx + 1,
                        rows=normalised_rows,
                    )
                )
    return tables


def _extract_figures(doc: Any) -> list[FigureRef]:
    """Page-level image references — each image rect on each
    page. The tool layer fills in `description` via vision_analyze
    when extract=full + cfg.document_describe_figures."""
    figures: list[FigureRef] = []
    for page_idx in range(doc.page_count):
        page = doc.load_page(page_idx)
        try:
            images = page.get_images(full=True)
        except Exception:  # noqa: BLE001
            continue
        for img in images:
            xref = img[0] if img else None
            if xref is None:
                continue
            try:
                rects = page.get_image_rects(xref)
            except Exception:  # noqa: BLE001
                rects = []
            if not rects:
                # No bbox known — still record the image as a
                # figure ref with bbox=None.
                figures.append(FigureRef(page=page_idx + 1, bbox=None))
                continue
            for rect in rects:
                figures.append(
                    FigureRef(
                        page=page_idx + 1,
                        bbox=(
                            float(rect.x0),
                            float(rect.y0),
                            float(rect.x1),
                            float(rect.y1),
                        ),
                    )
                )
    return figures


def _extract_metadata(doc: Any) -> dict[str, Any]:
    """PyMuPDF's metadata dict carries title / author / creator /
    creation date etc. We pass through known keys + the page
    count."""
    raw = doc.metadata or {}
    return {
        "title": (raw.get("title") or "").strip() or None,
        "author": (raw.get("author") or "").strip() or None,
        "subject": (raw.get("subject") or "").strip() or None,
        "keywords": (raw.get("keywords") or "").strip() or None,
        "creator": (raw.get("creator") or "").strip() or None,
        "producer": (raw.get("producer") or "").strip() or None,
        "creation_date": raw.get("creationDate") or None,
        "mod_date": raw.get("modDate") or None,
        "page_count": doc.page_count,
        "format": "PDF",
    }
