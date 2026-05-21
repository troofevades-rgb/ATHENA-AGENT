"""Per-format document extractors (T4-05.1).

One file per format. Each module exposes a top-level
``extract(path) -> DocumentResult`` function and optionally a
``rasterize_page(path, page, dpi) -> bytes`` for the OCR
fallback in the tool layer. Library choices stay isolated here
so a future format addition only touches one file.

Dispatch goes through :func:`for_extension` so the tool layer
doesn't have to know about per-format modules.
"""

from __future__ import annotations

from typing import Callable

from ..result import DocumentResult


# Map of lowercase extension (no leading dot) → extractor module
# name. Resolved lazily so importing the extractors package
# doesn't pay the cost of pulling PyMuPDF / python-docx unless
# the caller actually has a document of that type.
_EXTRACTORS: dict[str, str] = {
    "pdf": "athena.document.extractors.pdf",
    "docx": "athena.document.extractors.docx",
}


def supported_extensions() -> list[str]:
    """All extensions the dispatch table currently recognises."""
    return sorted(_EXTRACTORS.keys())


def for_extension(ext: str) -> Callable[..., DocumentResult] | None:
    """Resolve the per-format ``extract`` callable, or None when
    the extension isn't supported. Caller-side import means a
    missing optional dep on one format doesn't break others.
    """
    ext_lower = ext.lower().lstrip(".")
    module_name = _EXTRACTORS.get(ext_lower)
    if module_name is None:
        return None
    import importlib
    try:
        mod = importlib.import_module(module_name)
    except Exception:  # noqa: BLE001 — defensive on optional deps
        return None
    return getattr(mod, "extract", None)


def rasterize_for_extension(ext: str) -> Callable[..., bytes] | None:
    """Resolve the per-format ``rasterize_page`` callable for
    OCR fallback. Returns None when the format doesn't support
    it (DOCX has no page rasterization)."""
    ext_lower = ext.lower().lstrip(".")
    module_name = _EXTRACTORS.get(ext_lower)
    if module_name is None:
        return None
    import importlib
    try:
        mod = importlib.import_module(module_name)
    except Exception:  # noqa: BLE001
        return None
    return getattr(mod, "rasterize_page", None)
