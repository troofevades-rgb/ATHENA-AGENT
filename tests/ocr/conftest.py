"""OCR test fixtures.

The real tesseract binary may or may not be on the test
machine; tests use a stub backend at the OCRBackend Protocol
level so coverage stays consistent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from athena.ocr.contract import OCRBlock, OCRResult


class StubOCRBackend:
    """Deterministic stub. Used to test the tool layer + the
    contract without booting tesseract."""

    name = "ocr_stub"

    def __init__(
        self,
        *,
        available: bool = True,
        blocks: list[OCRBlock] | None = None,
        language: str | None = "eng",
        raise_on_recognize: Exception | None = None,
    ):
        self._available = available
        self._blocks = blocks or [
            OCRBlock(text="Hello world", bbox=(10, 10, 100, 40), confidence=92.0),
            OCRBlock(text="Second line", bbox=(10, 50, 110, 80), confidence=78.0),
        ]
        self._lang = language
        self._raise = raise_on_recognize
        self.recognize_calls: list[dict[str, Any]] = []

    def is_available(self) -> bool:
        return self._available

    def recognize(
        self,
        path: Path | str,
        *,
        langs: list[str] | None = None,
        with_boxes: bool = True,
    ) -> OCRResult:
        if self._raise is not None:
            raise self._raise
        self.recognize_calls.append({
            "path": str(path),
            "langs": list(langs) if langs else None,
            "with_boxes": with_boxes,
        })
        return OCRResult(blocks=list(self._blocks), language=self._lang)


@pytest.fixture
def stub_ocr() -> StubOCRBackend:
    return StubOCRBackend()
