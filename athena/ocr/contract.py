"""OCR backend contract — the shape every adapter satisfies (T4-06.1).

Normalized output across engines. The ocr tool maps each
backend's per-engine block shape into this so the model and
downstream consumers see one consistent surface regardless of
which engine ran.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Protocol


@dataclasses.dataclass(frozen=True)
class OCRBlock:
    """One recognized text block.

    `bbox` is (x0, y0, x1, y1) in pixel coordinates relative to
    the input image. The engine's coordinate convention is
    preserved as-is — pixel coordinates, top-left origin.

    `confidence` is 0..100 (the tesseract convention; engines
    that report 0..1 should multiply at the adapter boundary).
    The tool layer's min_confidence filter compares against
    this number directly.
    """

    text: str
    bbox: tuple[int, int, int, int]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": list(self.bbox),
            "confidence": round(float(self.confidence), 1),
        }


@dataclasses.dataclass
class OCRResult:
    """Full result of an OCR call."""

    blocks: list[OCRBlock]
    language: str | None = None

    def joined_text(self, separator: str = "\n") -> str:
        """Concatenate every block's text in recognition order.
        The default newline separator matches tesseract's
        default reading flow."""
        return separator.join(b.text for b in self.blocks if b.text)

    def to_dict(self, *, with_boxes: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {"text": self.joined_text()}
        if self.language is not None:
            d["language"] = self.language
        if with_boxes:
            d["blocks"] = [b.to_dict() for b in self.blocks]
        return d


class OCRBackend(Protocol):
    """The contract every OCR engine adapter implements.

    Backends should:
      - declare ``ocr=True`` in their static_capabilities() so
        the broker picks them up
      - prefer ``is_local=True`` for on-device engines
      - return blocks in recognition order with absolute pixel
        bounding boxes
      - never raise into the tool layer for an unknown
        language / format / engine error — return an empty
        OCRResult + log at WARNING (the tool's "no text"
        path then surfaces cleanly)
    """

    def is_available(self) -> bool:
        """Quick "this backend can run on this host" check.
        The tool consults this before routing; unavailable
        backends let the tool fall through to "no OCR
        configured" cleanly."""
        ...

    def recognize(
        self,
        path: Path | str,
        *,
        langs: list[str] | None = None,
        with_boxes: bool = True,
    ) -> OCRResult:
        """Recognize text in the image at ``path``.

        ``langs`` — ISO 639-2/T codes (e.g. ["eng", "fra"]).
        Engines that don't support multi-lang ignore extra
        entries and use the first.

        ``with_boxes`` — when False the adapter may skip the
        bounding-box collection step for speed; the result's
        ``blocks`` list still has one entry per recognized
        block, just without meaningful bbox values.
        """
        ...
