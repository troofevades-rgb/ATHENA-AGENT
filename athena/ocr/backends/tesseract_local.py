"""Local tesseract OCR backend via pytesseract (T4-06.1).

Tesseract is the mature, on-device OCR engine of choice. The
`pytesseract` Python wrapper provides a clean API over the
tesseract binary; first call to ``recognize`` invokes the
binary as a subprocess.

Engine isolation: ALL pytesseract / tesseract-binary specifics
live in this one file. Real cloud OCR adapters (e.g. Vision
API, AWS Textract) land alongside as separate modules with the
same Protocol shape; vendor specifics never leak into the tool
layer.

Installation requirements (documented in the reference doc):
  - ``pip install pytesseract`` (Python wrapper)
  - tesseract binary on PATH:
      Windows  : ``scoop install tesseract`` (or UB-Mannheim build)
      macOS    : ``brew install tesseract``
      Linux    : ``apt install tesseract-ocr``
  - Optional language packs:
      ``tesseract-langpack-<lang>`` apt packages, or copy the
      .traineddata files into ``$TESSDATA_PREFIX``

Without the binary, is_available() returns False and the broker
falls through cleanly — athena startup is never blocked.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from ...providers import register_provider
from ...providers.base import Capabilities, Provider
from ..contract import OCRBlock, OCRResult

logger = logging.getLogger(__name__)


@register_provider
class TesseractLocalBackend(Provider):
    """Local tesseract OCR backend.

    Declares ``Capabilities(ocr=True, is_local=True,
    tool_calls=False, streaming=False)`` so the broker prefers
    it under default local-preferred config. Capability-only
    provider — same shape as T4-04's audio_whisper_local and
    T6-05's stub_video_local; chat methods raise.
    """

    name: str = "ocr_tesseract_local"
    requires_api_key: bool = False

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        return Capabilities(
            ocr=True,
            is_local=True,
            tool_calls=False,
            streaming=False,
        )

    def __init__(self, api_key: str | None = None, **kwargs: Any):
        super().__init__(api_key=api_key, **kwargs)
        self._cfg_override = kwargs.get("cfg")

    # ----- chat ABC plumbing — not a chat backend -----

    def stream_chat(self, **kwargs: Any):  # noqa: D401
        raise NotImplementedError(
            "ocr_tesseract_local is an OCR backend, not a chat "
            "provider; route via MediaRegistry.backend_for('ocr')"
        )

    def parse_tool_calls(self, content: str, raw_response: dict[str, Any]):
        return content, []

    # ----- OCRBackend protocol -----

    def is_available(self) -> bool:
        """True iff (a) pytesseract is importable AND (b) the
        tesseract binary can be located. The tool layer
        consults this before routing; an unavailable backend
        lets the tool surface 'no OCR configured' cleanly."""
        try:
            import pytesseract  # noqa: F401
        except Exception:
            return False
        cfg = self._load_cfg()
        ocr_cfg = getattr(cfg, "ocr", None)
        cmd_override = ocr_cfg.tesseract_cmd if ocr_cfg is not None else None
        if cmd_override:
            return Path(cmd_override).exists()
        return shutil.which("tesseract") is not None

    def recognize(
        self,
        path: Path | str,
        *,
        langs: list[str] | None = None,
        with_boxes: bool = True,
    ) -> OCRResult:
        """Recognize text via pytesseract. Returns empty result
        on any engine failure rather than raising — the tool
        layer's "no text" path handles that gracefully."""
        try:
            import pytesseract
        except Exception as e:  # noqa: BLE001
            logger.warning("pytesseract import failed: %s", e)
            return OCRResult(blocks=[])

        cfg = self._load_cfg()
        ocr_cfg = getattr(cfg, "ocr", None)
        cmd_override = ocr_cfg.tesseract_cmd if ocr_cfg is not None else None
        if cmd_override:
            pytesseract.pytesseract.tesseract_cmd = str(cmd_override)

        lang_str = "+".join(langs or ["eng"])

        try:
            if with_boxes:
                # image_to_data returns one row per word with
                # bbox + confidence. We coalesce blocks
                # (tesseract's `block_num` field) so callers
                # get reasonable paragraph-sized chunks rather
                # than per-word noise.
                data = pytesseract.image_to_data(
                    str(path),
                    lang=lang_str,
                    output_type=pytesseract.Output.DICT,
                )
            else:
                # Plain text — faster than image_to_data.
                text = pytesseract.image_to_string(
                    str(path), lang=lang_str,
                )
                return OCRResult(
                    blocks=[OCRBlock(text=text.strip(), bbox=(0, 0, 0, 0),
                                     confidence=0.0)],
                    language=lang_str,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("tesseract recognize failed on %s: %s", path, e)
            return OCRResult(blocks=[])

        return OCRResult(
            blocks=_coalesce_blocks(data),
            language=lang_str,
        )

    # ----- internals -----

    def _load_cfg(self):
        if self._cfg_override is not None:
            return self._cfg_override
        from ...config import load_config
        return load_config()


# ---------------------------------------------------------------
# helpers
# ---------------------------------------------------------------


def _coalesce_blocks(data: dict[str, list[Any]]) -> list[OCRBlock]:
    """Group pytesseract's per-word rows into block-level
    OCRBlocks.

    pytesseract's image_to_data returns parallel lists keyed by
    ``level`` (1=page, 2=block, 3=para, 4=line, 5=word). Block-
    level entries (level==2) carry the block's coordinates;
    words at the same ``block_num`` belong to that block.

    We collect every level==5 row, group by (page, block) tuple,
    take the bbox covering all words in the group, and average
    the confidences. Recognition order is preserved (pytesseract
    emits rows in reading order).
    """
    n = len(data.get("level", []))
    grouped: dict[tuple[int, int, int], dict[str, Any]] = {}
    order: list[tuple[int, int, int]] = []

    for i in range(n):
        if int(data["level"][i]) != 5:
            continue
        word = str(data["text"][i] or "").strip()
        if not word:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1.0
        if conf < 0:
            # tesseract returns -1 for "no confidence" — skip
            # rather than poison the average.
            continue
        page = int(data.get("page_num", [1] * n)[i] or 1)
        block = int(data["block_num"][i])
        para = int(data.get("par_num", [0] * n)[i] or 0)
        key = (page, block, para)
        if key not in grouped:
            grouped[key] = {
                "words": [],
                "confs": [],
                "left": int(data["left"][i]),
                "top": int(data["top"][i]),
                "right": int(data["left"][i]) + int(data["width"][i]),
                "bottom": int(data["top"][i]) + int(data["height"][i]),
            }
            order.append(key)
        g = grouped[key]
        g["words"].append(word)
        g["confs"].append(conf)
        g["left"] = min(g["left"], int(data["left"][i]))
        g["top"] = min(g["top"], int(data["top"][i]))
        g["right"] = max(
            g["right"], int(data["left"][i]) + int(data["width"][i]),
        )
        g["bottom"] = max(
            g["bottom"], int(data["top"][i]) + int(data["height"][i]),
        )

    out: list[OCRBlock] = []
    for key in order:
        g = grouped[key]
        text = " ".join(g["words"])
        avg_conf = sum(g["confs"]) / max(1, len(g["confs"]))
        out.append(OCRBlock(
            text=text,
            bbox=(g["left"], g["top"], g["right"], g["bottom"]),
            confidence=avg_conf,
        ))
    return out
