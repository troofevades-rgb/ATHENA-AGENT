"""ocr tool (T4-06.2).

`ocr(path, languages?, with_boxes?)` reads text from an image
or rasterized page via the manifest-resolved OCR backend.

Returned as JSON the model parses:

  {
    "available": true,
    "backend": "ocr_tesseract_local",
    "text": "...",
    "blocks": [
      {"text": "...", "bbox": [x0,y0,x1,y1], "confidence": 87.3},
      ...
    ],
    "language": "eng"
  }

Failure / unavailability is always structured (never raises
into the model loop):

  {"available": false, "reason": "no OCR backend configured"}
  {"available": false, "error": "file not found: /no/such.png"}

Composable: T4-05 document_analyze and T4-01 vision_analyze
both reach for ``ocr_recognize(path, *, cfg, backend?,
languages?, min_confidence?)`` directly when they need to
read text in an image, bypassing the @tool JSON layer.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..config import load_config
from ..tools.registry import tool
from .contract import OCRBackend, OCRBlock, OCRResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------
# Backend resolution
# ---------------------------------------------------------------


def _resolve_backend(cfg: Any) -> OCRBackend | None:
    """Find the OCR backend via the T5-05 broker. Returns None
    when no provider declares ``ocr`` or the chosen class
    can't be constructed / isn't actually available on this
    host (e.g. tesseract binary missing)."""
    from . import backends  # noqa: F401 — trigger registration
    from ..media.registry import MediaRegistry

    reg = MediaRegistry(cfg=cfg)
    cls = reg.backend_for("ocr")
    if cls is None:
        logger.info("ocr: no backend declares the ocr capability")
        return None
    try:
        instance = cls()
    except Exception as e:  # noqa: BLE001
        logger.warning("ocr: backend %r construction failed: %s", cls.__name__, e)
        return None
    # is_available is the runtime check (engine binary present,
    # auth ok, etc.). Class-level "declared" can be true while
    # the runtime check fails — the broker doesn't know.
    if not getattr(instance, "is_available", lambda: True)():
        logger.info(
            "ocr: backend %r declared but not available on this host",
            cls.__name__,
        )
        return None
    return instance  # type: ignore[return-value]


# ---------------------------------------------------------------
# ocr_recognize — composable helper for T4-05 / T4-01
# ---------------------------------------------------------------


def ocr_recognize(
    path: Path | str,
    *,
    cfg: Any | None = None,
    backend: OCRBackend | None = None,
    languages: list[str] | None = None,
    with_boxes: bool = True,
    min_confidence: float | None = None,
) -> OCRResult:
    """Composable end-to-end OCR. Returns the raw OCRResult
    (bypasses the tool layer's JSON formatting) so callers
    like T4-05 document_analyze can splice OCR'd text directly
    into their own result.

    ``min_confidence`` — drop blocks below the threshold. When
    None, reads ``cfg.ocr_min_confidence`` (default 0 = no
    filter).

    No backend → empty OCRResult (no error). Same shape as the
    transcribe_track helper in T4-04.
    """
    cfg = cfg if cfg is not None else load_config()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"OCR input not found: {path}")

    if backend is None:
        backend = _resolve_backend(cfg)
    if backend is None:
        return OCRResult(blocks=[])

    ocr_cfg = getattr(cfg, "ocr", None)
    langs = languages or list(
        (ocr_cfg.languages if ocr_cfg is not None else ["eng"]) or ["eng"]
    )

    try:
        result = backend.recognize(p, langs=langs, with_boxes=with_boxes)
    except Exception as e:  # noqa: BLE001
        logger.warning("ocr: backend %r raised on %s: %s", type(backend).__name__, path, e)
        return OCRResult(blocks=[])

    threshold = (
        min_confidence if min_confidence is not None
        else float(
            (ocr_cfg.min_confidence if ocr_cfg is not None else 0) or 0
        )
    )
    if threshold > 0:
        filtered = [b for b in result.blocks if b.confidence >= threshold]
        result = OCRResult(blocks=filtered, language=result.language)

    return result


# ---------------------------------------------------------------
# Public entry — registered as @tool below
# ---------------------------------------------------------------


def _run(
    *,
    path: str | None = None,
    languages: list[str] | None = None,
    with_boxes: bool = True,
    min_confidence: float | None = None,
    _cfg: Any = None,
    _backend: OCRBackend | None = None,
) -> str:
    cfg = _cfg if _cfg is not None else load_config()
    ocr_cfg = getattr(cfg, "ocr", None)
    if ocr_cfg is not None and not ocr_cfg.enabled:
        return json.dumps({
            "available": False,
            "error": "cfg.ocr.enabled=False; operator disabled OCR",
        })
    if not path:
        return json.dumps({
            "available": False, "error": "path is required",
        })
    p = Path(path)
    if not p.exists():
        return json.dumps({
            "available": False, "error": f"file not found: {path}",
        })

    backend = _backend if _backend is not None else _resolve_backend(cfg)
    if backend is None:
        return json.dumps({
            "available": False,
            "reason": (
                "no OCR backend configured — declare an ocr-capable "
                "provider (e.g. install tesseract + pytesseract) or "
                "set cfg.ocr_enabled=False"
            ),
        })

    try:
        result = ocr_recognize(
            p, cfg=cfg, backend=backend,
            languages=languages,
            with_boxes=with_boxes,
            min_confidence=min_confidence,
        )
    except FileNotFoundError as e:
        return json.dumps({"available": False, "error": str(e)})
    except Exception as e:  # noqa: BLE001
        logger.exception("ocr: recognize failed")
        return json.dumps({
            "available": True,
            "error": f"ocr failed: {type(e).__name__}: {e}",
            "path": str(p),
        })

    payload: dict[str, Any] = {
        "available": True,
        "backend": getattr(backend, "name", type(backend).__name__),
        "path": str(p),
        **result.to_dict(with_boxes=with_boxes),
    }
    return json.dumps(payload, ensure_ascii=False)


@tool(
    name="ocr",
    toolset="vision",  # same toolset as vision / video / audio
    description=(
        "Read text from an image or scanned page. Returns the\n"
        "recognized text plus optional per-block bounding boxes\n"
        "and confidence scores (0-100). Use OCR when the\n"
        "question is *what does the text in this image say* —\n"
        "use vision_analyze when the question is *what is in\n"
        "this picture*. The two are different jobs; OCR reads,\n"
        "vision describes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "languages": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "ISO 639-2/T language codes. Default ['eng']. "
                    "Multi-language: ['eng','fra']. Each non-"
                    "default language requires the matching "
                    "tessdata file installed."
                ),
            },
            "with_boxes": {
                "type": "boolean",
                "description": (
                    "Include per-block bounding boxes + confidence "
                    "in the result. Default true."
                ),
            },
            "min_confidence": {
                "type": "number",
                "description": (
                    "Drop blocks below this OCR confidence (0-100). "
                    "Default 0 (no filter). 60+ filters noisy "
                    "recognitions."
                ),
            },
        },
        "required": ["path"],
    },
)
def ocr(**kwargs: Any) -> str:
    return _run(**kwargs)
