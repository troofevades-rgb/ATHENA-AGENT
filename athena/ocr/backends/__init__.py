"""OCR backends — one file per engine.

Importing this package side-effect-registers any adapter
whose module imports successfully. The in-tree default is
:mod:`athena.ocr.backends.tesseract_local` (tesseract via
pytesseract). Real cloud / alternative engines land alongside
one per file when needed.
"""

from __future__ import annotations

# Trigger registration. Wrapped in try/except so a missing
# optional dep (pytesseract not installed, tesseract binary
# not on PATH) doesn't break athena startup; the broker
# simply finds no OCR backend and the ocr tool surfaces
# "no backend configured" cleanly.
try:
    from . import tesseract_local as _ts  # noqa: F401
except Exception:  # noqa: BLE001 — defensive at import time
    import logging
    logging.getLogger(__name__).debug(
        "tesseract_local OCR backend not loaded "
        "(pytesseract missing or import failed)",
        exc_info=True,
    )
