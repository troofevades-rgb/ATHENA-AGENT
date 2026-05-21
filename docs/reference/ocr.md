# `ocr` — read text from images and scanned pages

Reads text out of an image / rasterized page via a manifest-resolved OCR engine. **Local-preferred by default** — text in images never leaves the machine.

## OCR vs. vision — different jobs

| Question | Right tool |
|---|---|
| "What is in this picture?" | `vision_analyze` (describes content) |
| "What does the text in this image say?" | `ocr` (reads characters) |
| "Describe this screenshot of an email" | both — `vision_analyze describe` for layout, `ocr` for body text |

Vision describes; OCR reads. The two route through different backends and the tool layer never mixes them. T4-01 explicitly listed OCR as a non-goal; T4-06 fills the gap.

## Tool result shape

```json
{
  "available": true,
  "backend": "ocr_tesseract_local",
  "path": "/abs/path/scan.png",
  "text": "Line one\nLine two\n…",
  "blocks": [
    {"text": "Line one", "bbox": [10, 10, 220, 38], "confidence": 92.3},
    {"text": "Line two", "bbox": [10, 42, 230, 70], "confidence": 88.1}
  ],
  "language": "eng"
}
```

Errors are always structured (never raise into the model loop):

```json
{"available": false, "reason": "no OCR backend configured"}
{"available": false, "error": "file not found: /no/such.png"}
{"available": false, "error": "ocr_enabled=False; operator disabled OCR"}
```

## Modes / arguments

| Arg | Default | Meaning |
|---|---|---|
| `path` | — (required) | Image / rasterized page file. |
| `languages` | `cfg.ocr_languages` (`["eng"]`) | ISO 639-2/T codes. Multi-language: `["eng", "fra"]`. Each non-default language needs the matching `tessdata` file installed. |
| `with_boxes` | `true` | Include per-block bbox + confidence. `false` runs the faster text-only path. |
| `min_confidence` | `cfg.ocr_min_confidence` (`0`) | Drop blocks below this engine-reported confidence (0–100). `0` = no filter. `60+` filters most noisy recognitions. |

## Confidence is the honesty knob

OCR engines fail silently — bad scans produce plausible-looking nonsense. Each block carries the engine's confidence (0–100, tesseract convention; cloud engines reporting 0–1 are scaled at the adapter boundary). The model can flag low-confidence regions instead of inventing text:

```
> ocr path=invoice_scan.png min_confidence=60
… returns only the blocks tesseract is confident about;
the model sees what's reliably readable and what isn't.
```

## Manifest-driven backend resolution

`MediaRegistry.backend_for("ocr")` finds the first registered provider whose capability manifest declares `ocr=True`. With `cfg.media_backend_prefer = "local"` (default), any backend with `is_local=True` wins.

In-tree backend: `athena/ocr/backends/tesseract_local.py` — wraps `pytesseract` over a system tesseract binary. Declares `Capabilities(ocr=True, is_local=True, tool_calls=False, streaming=False)`.

No backend declares `ocr` (or the engine isn't installed on this host) → `{"available": false, "reason": "no OCR backend configured"}`. **Not an error** — the unavailable-≠-error invariant runs through the whole T4 stack.

## Composable helper

T4-05 document_analyze and T4-01 vision_analyze both call this directly when they need to read text:

```python
from athena.ocr.tools import ocr_recognize

result = ocr_recognize(
    rasterized_page_path,
    cfg=cfg,
    languages=["eng"],
    min_confidence=60,
)
# result.blocks → list[OCRBlock(text, bbox, confidence)]
# result.joined_text() → concatenated reading-order text
```

Returns the raw `OCRResult`, bypasses the tool's JSON layer. Empty result on no-backend / engine failure / missing file → caller chooses how to surface it.

## Installation

```bash
pip install pytesseract
```

Plus the tesseract binary on PATH:

| Platform | Command |
|---|---|
| Windows | `scoop install tesseract` (or [UB-Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki)) |
| macOS | `brew install tesseract` |
| Debian/Ubuntu | `apt install tesseract-ocr` |

Multi-language: install the matching `tessdata` pack per language (e.g. `apt install tesseract-ocr-fra` for French) or copy the `.traineddata` file into `$TESSDATA_PREFIX`.

If the binary isn't on PATH but lives at a known location, set `cfg.ocr_tesseract_cmd = "C:/path/to/tesseract.exe"`.

## Configuration

```toml
ocr_enabled = true
ocr_backend_prefer = "local"
ocr_languages = ["eng"]
ocr_min_confidence = 0          # 0 keeps everything; 60+ filters noise
ocr_tesseract_cmd = ""          # "" → PATH lookup; explicit path overrides
```

## Consumed by

- **T4-05 document_analyze**: scanned PDF pages (no text layer) are rasterized + handed to `ocr_recognize`, then merged back into the document result so mixed (born-digital + scanned) documents come back whole.
- **T4-01 vision_analyze**: any "what does the text in this image say" path can call `ocr_recognize` for the text and `describe` for the picture-level reasoning.

## Non-goals

- **Layout reconstruction.** OCR returns blocks in recognition order with bboxes; reassembling exact document layout (columns, headers, tables across pages) is the caller's job — document_analyze does this for PDFs.
- **Handwriting recognition** on engines that don't support it. Tesseract is print-text-optimized; handwriting needs a different engine adapter (e.g. cloud Vision API).
- **Bulk preprocessing.** Deskew, threshold, contrast normalize — left to the caller / the rasterizer. The OCR tool is a thin pass-through.
- **Streaming / live OCR.** Per-image only; multi-page is the caller's loop.

## Reference

- Contract: `athena/ocr/contract.py`
- Backend: `athena/ocr/backends/tesseract_local.py`
- Tool + composable helper: `athena/ocr/tools.py`
- Vision sibling: `docs/reference/vision-analyze.md`
- Document consumer: `docs/reference/document.md` (T4-05)
