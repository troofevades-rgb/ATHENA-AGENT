"""document_analyze tool (T4-05.2).

One tool, five modes:

  text       reading-order text only
  structure  text + heading/section outline (default)
  tables     just the table data
  metadata   just title/author/dates/format
  full       all of the above PLUS optional figure descriptions
             via T4-01 vision when document_describe_figures is on

Scanned PDF pages (no text layer) route to T4-06 OCR via the
composable ``ocr_recognize`` helper; the OCR'd text is spliced
into the per-page text dict and merged into the document's
full text so a mixed document (born-digital + scanned pages)
comes back whole. No OCR backend → those pages return empty
with a flagged note (in ``scanned_pages`` but not ``ocr_pages``),
NOT an error.

Per-call streaming progress callback so a CLI surface can show
"3/12 pages processed" on a large document.

Every read sha256s the source file + writes a JSONL audit row
+ a parsed-result artifact under ``cfg.document_output_dir``
(default ``<profile_dir>/documents/``). Same provenance shape
as T4-01 vision / T4-02 video / T4-04 audio.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from ..config import load_config, profile_dir
from ..tools.registry import tool
from ..vision.hashlog import HashLogger, sha256_file
from .extractors import for_extension, rasterize_for_extension
from .result import DocumentResult, FigureRef

logger = logging.getLogger(__name__)


VALID_MODES = ("text", "structure", "tables", "metadata", "full")


_DOCUMENT_AUDIT_FILENAME = "document_audit.jsonl"


def document_audit_path(profile_dir_path: Path | str) -> Path:
    return Path(profile_dir_path) / _DOCUMENT_AUDIT_FILENAME


# OCRFn — what _run accepts as an injection point for the
# OCR call. Production wires it to athena.ocr.tools.ocr_recognize;
# tests pass a stub. Returns the same dict shape as
# OCRResult.to_dict() — so the integration is "give me a path
# + cfg + languages, get back text + blocks + confidence".
OCRFn = Callable[[Path], dict]

# VisionFn — describe a single image bytes/path and return a
# string. Reuses T4-01's vision_analyze describe shape.
VisionFn = Callable[[bytes], str]


# ---------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------


def _resolve_paths(cfg: Any) -> dict[str, Path]:
    pdir = profile_dir(getattr(cfg, "profile", "default"))
    out_dir = (
        Path(cfg.document_output_dir)
        if getattr(cfg, "document_output_dir", None)
        else pdir / "documents"
    )
    return {
        "profile": pdir,
        "audit": document_audit_path(pdir),
        "out_dir": out_dir,
    }


# ---------------------------------------------------------------
# OCR + vision factories
# ---------------------------------------------------------------


def _default_ocr_fn(cfg: Any) -> OCRFn | None:
    """Build an OCRFn that routes through T4-06's ocr_recognize.
    Returns None when cfg.document_ocr_fallback=False OR when
    no OCR backend is configured on this host (the broker
    finds none / tesseract binary missing / etc.)."""
    if not getattr(cfg, "document_ocr_fallback", True):
        return None
    try:
        from ..ocr.tools import ocr_recognize
    except Exception:  # noqa: BLE001
        return None

    def _fn(image_path: Path) -> dict:
        result = ocr_recognize(image_path, cfg=cfg)
        return result.to_dict(with_boxes=True)

    return _fn


def _default_vision_fn(cfg: Any) -> VisionFn | None:
    """Build a VisionFn that routes through T4-01's vision_analyze
    describe mode. Returns None when figure description is off
    or vision isn't usable on this host."""
    if not getattr(cfg, "document_describe_figures", False):
        return None
    if not getattr(cfg, "vision_enabled", True):
        return None
    try:
        from ..vision.analyze import _run as vision_run
    except Exception:  # noqa: BLE001
        return None
    import base64
    import tempfile

    def _fn(image_bytes: bytes) -> str:
        # vision_analyze takes a path, not bytes — drop to a
        # short-lived temp file. The temp file lives long
        # enough for vision_analyze to process; we clean up
        # on exit.
        with tempfile.NamedTemporaryFile(
            suffix=".png", delete=False,
        ) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name
        try:
            out = vision_run(
                mode="describe",
                path=tmp_path,
                prompt="Describe this figure in concrete detail.",
                _cfg=cfg,
            )
            try:
                data = json.loads(out)
            except json.JSONDecodeError:
                return ""
            return str(data.get("answer", ""))
        finally:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass

    return _fn


# ---------------------------------------------------------------
# OCR fallback: rasterize scanned pages + splice text in
# ---------------------------------------------------------------


def _ocr_scanned_pages(
    result: DocumentResult,
    *,
    path: Path,
    cfg: Any,
    ocr_fn: OCRFn,
    progress: Callable[[int, int], None] | None = None,
) -> DocumentResult:
    """For every page in ``result.scanned_pages``, rasterize it
    and run OCR. Splice the OCR'd text into ``result.page_texts``
    and rebuild ``result.text`` from the updated per-page slice.

    Returns a NEW DocumentResult (the input is not mutated in
    place). Pages where rasterization fails or OCR returns
    empty stay in ``scanned_pages`` but don't land in
    ``ocr_pages`` — operator sees "we tried, no text came out".
    """
    rasterize = rasterize_for_extension(path.suffix)
    if rasterize is None:
        # Format doesn't support rasterization (DOCX) — nothing
        # to do for scanned pages. The format also doesn't have
        # scanned pages in practice (DOCX is born-digital).
        return result

    dpi = int(getattr(cfg, "document_rasterize_dpi", 200))
    new_page_texts = dict(result.page_texts)
    ocr_pages: list[int] = []

    for i, page_no in enumerate(result.scanned_pages, start=1):
        if progress is not None:
            progress(i, len(result.scanned_pages))
        try:
            png_bytes = rasterize(path, page_no, dpi=dpi)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "document: rasterize page %d failed: %s", page_no, e,
            )
            continue
        # Write to a temp file — ocr_recognize takes paths.
        import tempfile
        with tempfile.NamedTemporaryFile(
            suffix=".png", delete=False,
        ) as tmp:
            tmp.write(png_bytes)
            tmp_path = Path(tmp.name)
        try:
            ocr_result = ocr_fn(tmp_path)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "document: OCR on page %d failed: %s", page_no, e,
            )
            ocr_result = {"text": ""}
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

        ocr_text = (ocr_result or {}).get("text", "")
        if ocr_text.strip():
            new_page_texts[page_no] = ocr_text
            ocr_pages.append(page_no)

    # Rebuild full text from per-page slices in page order.
    # PyMuPDF original used \f between pages; keep that.
    rebuilt = "\f".join(
        new_page_texts.get(i, "") for i in range(1, result.pages + 1)
    )
    return DocumentResult(
        text=rebuilt,
        pages=result.pages,
        outline=result.outline,
        tables=result.tables,
        metadata=result.metadata,
        scanned_pages=result.scanned_pages,
        ocr_pages=ocr_pages,
        figures=result.figures,
        page_texts=new_page_texts,
    )


# ---------------------------------------------------------------
# Figure description via vision
# ---------------------------------------------------------------


def _describe_figures(
    result: DocumentResult,
    *,
    path: Path,
    cfg: Any,
    vision_fn: VisionFn,
) -> DocumentResult:
    """For each figure with a bbox, render a small image of the
    region and ask vision_analyze to describe it. Mutates only
    via a fresh result (figures list rebuilt with descriptions)."""
    rasterize = rasterize_for_extension(path.suffix)
    if rasterize is None or not result.figures:
        return result

    # PyMuPDF lets us crop a page region — but a clean cross-
    # format escape is to rasterize the WHOLE page containing
    # the figure and let vision describe it (the bbox tells the
    # model where in the page to focus). For deeper integration
    # a future change can render bounded sub-images; for now,
    # whole-page is the safe shape.
    dpi = int(getattr(cfg, "document_rasterize_dpi", 200))
    described: list[FigureRef] = []
    cache_by_page: dict[int, bytes] = {}

    for fig in result.figures:
        if fig.page < 1:
            described.append(fig)
            continue
        if fig.page not in cache_by_page:
            try:
                cache_by_page[fig.page] = rasterize(path, fig.page, dpi=dpi)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "document: rasterize for figure on page %d failed: %s",
                    fig.page, e,
                )
                described.append(fig)
                continue
        try:
            desc = vision_fn(cache_by_page[fig.page])
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "document: figure describe failed on page %d: %s", fig.page, e,
            )
            desc = None
        if desc:
            described.append(FigureRef(
                page=fig.page, bbox=fig.bbox, description=desc,
            ))
        else:
            described.append(fig)

    return DocumentResult(
        text=result.text,
        pages=result.pages,
        outline=result.outline,
        tables=result.tables,
        metadata=result.metadata,
        scanned_pages=result.scanned_pages,
        ocr_pages=result.ocr_pages,
        figures=described,
        page_texts=result.page_texts,
    )


# ---------------------------------------------------------------
# Artifact writer
# ---------------------------------------------------------------


def _write_artifact(
    result: DocumentResult,
    *,
    out_dir: Path,
    source_sha: str,
    source_path: Path,
) -> Path:
    """Write the parsed result as JSON under ``out_dir``.
    Deterministic filename so reruns overwrite predictably."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{source_path.stem}_{source_sha[:8]}"
    json_path = out_dir / f"{stem}.json"
    json_path.write_text(
        json.dumps(result.normalized(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return json_path


# ---------------------------------------------------------------
# Mode-aware result trimming
# ---------------------------------------------------------------


def _trim_for_mode(result: dict, mode: str) -> dict:
    """The tool result shape stays the same across modes
    (predictable for the model), but modes can omit irrelevant
    fields to keep the payload tight. The returned dict still
    includes ``mode`` + ``path`` + ``sha256`` so the model
    sees the full identity."""
    if mode == "text":
        return {
            "text": result.get("text", ""),
            "pages": result.get("pages", 0),
            "scanned_pages": result.get("scanned_pages", []),
            "ocr_pages": result.get("ocr_pages", []),
        }
    if mode == "structure":
        return {
            "text": result.get("text", ""),
            "pages": result.get("pages", 0),
            "outline": result.get("outline", []),
            "scanned_pages": result.get("scanned_pages", []),
            "ocr_pages": result.get("ocr_pages", []),
        }
    if mode == "tables":
        return {
            "tables": result.get("tables", []),
            "pages": result.get("pages", 0),
        }
    if mode == "metadata":
        return {"metadata": result.get("metadata", {})}
    # full → return everything
    return result


# ---------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------


def _run(
    *,
    path: str | None = None,
    extract: str | None = None,
    _cfg: Any = None,
    _ocr_fn: OCRFn | None = None,
    _vision_fn: VisionFn | None = None,
    _progress: Callable[[int, int], None] | None = None,
) -> str:
    cfg = _cfg if _cfg is not None else load_config()
    if not getattr(cfg, "document_analyze_enabled", True):
        return json.dumps({
            "available": False,
            "error": "document_analyze_enabled=False; operator disabled document_analyze",
        })

    mode = extract or getattr(cfg, "document_default_extract", "structure")
    if mode not in VALID_MODES:
        return json.dumps({
            "available": False,
            "error": f"unknown extract mode {mode!r}; choose from {list(VALID_MODES)}",
        })

    if not path:
        return json.dumps({"available": False, "error": "path is required"})
    p = Path(path)
    if not p.exists():
        return json.dumps({
            "available": False, "error": f"file not found: {path}",
        })

    ext = p.suffix.lower().lstrip(".")
    extractor = for_extension(ext)
    if extractor is None:
        return json.dumps({
            "available": False,
            "reason": (
                f"unsupported document type: {ext!r}; "
                f"supported formats: pdf, docx"
            ),
        })

    paths = _resolve_paths(cfg)
    audit = HashLogger(paths["audit"])
    sha = sha256_file(p)

    try:
        result = extractor(p)
    except Exception as e:  # noqa: BLE001
        logger.exception("document_analyze: extractor failed")
        return json.dumps({
            "available": True,
            "error": f"extract failed: {type(e).__name__}: {e}",
            "path": str(p), "sha256": sha,
        })

    # OCR fallback for scanned pages.
    if result.scanned_pages:
        ocr_fn = _ocr_fn if _ocr_fn is not None else _default_ocr_fn(cfg)
        if ocr_fn is not None:
            result = _ocr_scanned_pages(
                result, path=p, cfg=cfg, ocr_fn=ocr_fn,
                progress=_progress,
            )

    # Optional figure description via vision (mode=full + opt-in).
    if mode == "full":
        vision_fn = _vision_fn if _vision_fn is not None else _default_vision_fn(cfg)
        if vision_fn is not None and result.figures:
            result = _describe_figures(
                result, path=p, cfg=cfg, vision_fn=vision_fn,
            )

    artifact_path = _write_artifact(
        result, out_dir=paths["out_dir"],
        source_sha=sha, source_path=p,
    )

    audit.log(
        mode=mode, path=p, sha256=sha,
        size_bytes=p.stat().st_size,
        extra={
            "format": result.metadata.get("format"),
            "pages": result.pages,
            "scanned_pages": list(result.scanned_pages),
            "ocr_pages": list(result.ocr_pages),
            "outline_entries": len(result.outline),
            "table_count": len(result.tables),
            "figure_count": len(result.figures),
            "artifact_path": str(artifact_path),
        },
    )

    payload = {
        "available": True,
        "mode": mode,
        "path": str(p),
        "sha256": sha,
        "artifact_path": str(artifact_path),
        **_trim_for_mode(result.normalized(), mode),
    }
    return json.dumps(payload, ensure_ascii=False)


@tool(
    name="document_analyze",
    toolset="vision",
    description=(
        "Extract clean text, heading/section outline, tables, and\n"
        "metadata from PDF / DOCX. Modes:\n"
        "  text       — reading-order text only\n"
        "  structure  — text + outline (default)\n"
        "  tables     — extracted tables\n"
        "  metadata   — title/author/dates/format only\n"
        "  full       — all of the above + figure descriptions\n"
        "               via vision when describe_figures is on\n"
        "Scanned PDF pages (no text layer) route to OCR (T4-06)\n"
        "and the OCR'd text is merged so mixed documents come\n"
        "back whole. No OCR backend → scanned pages flagged but\n"
        "empty (not an error)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "extract": {
                "type": "string",
                "enum": list(VALID_MODES),
                "description": (
                    "What to extract. Default 'structure' (text + "
                    "outline)."
                ),
            },
        },
        "required": ["path"],
    },
)
def document_analyze(**kwargs: Any) -> str:
    return _run(**kwargs)
