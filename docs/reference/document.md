# `document_analyze` — PDF + DOCX text, outline, tables, metadata

One tool, five modes. PDF + DOCX in-tree. Scanned PDF pages route to OCR (T4-06) and merge back so mixed documents come back whole.

## Modes

| Mode | Returns |
|---|---|
| `text` | reading-order text + `pages` + `scanned_pages` / `ocr_pages` |
| `structure` (default) | `text` + heading/section `outline` + scanned/OCR page lists |
| `tables` | extracted tables (rows × cols) |
| `metadata` | title / author / dates / format only |
| `full` | everything above + optional figure descriptions via T4-01 vision |

## Tool result shape

```json
{
  "available": true,
  "mode": "structure",
  "path": "/abs/spec.pdf",
  "sha256": "abcd…",
  "artifact_path": "/abs/profile/documents/spec_abcd1234.json",
  "text": "1. Introduction\n…\n2. Methods\n…",
  "pages": 24,
  "outline": [
    {"level": 1, "title": "Introduction", "page": 1},
    {"level": 1, "title": "Methods",      "page": 3},
    {"level": 2, "title": "Data sources", "page": 4},
    …
  ],
  "scanned_pages": [12, 13],
  "ocr_pages":     [12, 13]
}
```

`text` joins pages with form-feed (`\f`) for PDFs so a downstream consumer can re-split per page. DOCX has no page concept at parse time, so `pages = 0` and the text is one continuous string.

`mode=full` adds `tables`, `metadata`, `figures` (each with `bbox` and optional `description`).

Errors are structured (never raise into the model loop):

```json
{"available": false, "error": "file not found: /no/such.pdf"}
{"available": false, "reason": "unsupported document type: 'xlsx'; supported formats: pdf, docx"}
{"available": false, "error": "document_analyze_enabled=False; ..."}
```

## The scanned-page OCR fallback (the load-bearing piece)

PDFs commonly mix born-digital pages (selectable text) with scanned image pages (no text layer — a JPG inside a PDF wrapper). The extractor flags any page whose text layer is < 20 chars after strip as **scanned**. The tool then:

1. Rasterizes each scanned page via PyMuPDF at `cfg.document_rasterize_dpi` (200 default — OCR sweet spot)
2. Hands the PNG bytes to T4-06's `ocr_recognize`
3. Splices the OCR'd text into `page_texts[N]` and rebuilds `text` from per-page slices joined by form-feed
4. Records the OCR'd page in `ocr_pages` so the model can distinguish *born-digital* from *OCR'd*

`scanned_pages` lists every flagged page; `ocr_pages` is the subset that actually got OCR'd. The two together tell the operator exactly what happened: "we tried OCR on these, it succeeded on these."

### Graceful degrade

- **No OCR backend on this host** → `scanned_pages` stays populated, `ocr_pages` is empty, **NO error**. The unavailable-≠-error invariant runs through the whole T4 stack.
- **`cfg.document_ocr_fallback = false`** → OCR path is never even built. Same result shape (`scanned_pages` flagged, `ocr_pages` empty).
- **OCR returns empty text on a scanned page** → page stays flagged but doesn't enter `ocr_pages`. Operator sees: "we tried, no text came out" — usually means the scan is too noisy for confident recognition; bump `cfg.document_rasterize_dpi` to 300 or drop `cfg.ocr_min_confidence` to recover.

## Figure description via vision (opt-in, `full` mode only)

Set `cfg.document_describe_figures = true` and `vision_enabled = true`, then call `document_analyze extract=full`. Each figure embedded in the document gets a `description` field filled by T4-01's `vision_analyze describe` mode. The tool rasterizes the figure's containing page once (cached across multi-figure pages) and hands the bytes to vision.

```json
{
  "figures": [
    {
      "page": 4,
      "bbox": [120.5, 200.0, 480.5, 360.0],
      "description": "A scatter plot of measurement vs time. Two clusters visible …"
    },
    …
  ]
}
```

Off by default — figure description adds latency + tokens and isn't needed for every read.

## Hash-log + persistent artifact

Every call writes:

- `<profile_dir>/document_audit.jsonl` — one JSONL row per call with `{ts, mode, path, sha256, bytes, extra: {format, pages, scanned_pages, ocr_pages, outline_entries, table_count, figure_count, artifact_path}}`. Same provenance shape as T4-01 vision / T4-02 video / T4-04 audio.
- `<profile_dir>/documents/<source-stem>_<sha8>.json` — the **full** normalized result as JSON, regardless of mode. The model gets a mode-trimmed view; the operator gets the complete parse on disk for grep / inspection / re-use.

Deterministic filename via the source SHA-8 means reruns on the same document overwrite predictably.

## Configuration

```toml
document_analyze_enabled = true
document_default_extract = "structure"   # text|structure|tables|metadata|full
document_ocr_fallback = true             # use T4-06 OCR for scanned pages
document_describe_figures = false        # use T4-01 vision for figures (opt-in)
document_rasterize_dpi = 200             # PNG render DPI for scanned/figure pages
document_output_dir = ""                 # "" → <profile>/documents/
```

## Dependencies

- `pymupdf` (the `fitz` import) — PDF parser + rasterizer. Already in athena's runtime today; `pip install pymupdf` if missing.
- `python-docx` — DOCX parser. Already in athena's runtime today.
- **T4-06 OCR** (optional) — needed for scanned PDF pages. Without it, `scanned_pages` stays flagged but `ocr_pages` is empty.
- **T4-01 vision** (optional) — needed for `extract=full` figure description with `document_describe_figures=true`.

## What this is NOT

- **Bulk format support.** PDF + DOCX only. PPTX / RTF / ODT / HTML are out of scope; future format adapters land alongside one per file with the same Protocol.
- **Layout reconstruction.** Reading-order text + outline + table grid is what comes out. Pixel-perfect document reproduction is a different problem.
- **Form filling / annotation extraction.** Form fields, comments, and annotations are skipped; PyMuPDF can read them but they're a separate phase if needed.
- **OCR for DOCX.** DOCX is born-digital; if it has scanned images embedded as figures, vision describes them (when `describe_figures` is on), but OCR doesn't fire on DOCX pages because there are no pages to rasterize.
- **Live / streaming parsing.** The tool reads the complete file from disk; chunked or partial reads aren't supported.

## Reference

- Normalized result: `athena/document/result.py`
- PDF extractor: `athena/document/extractors/pdf.py`
- DOCX extractor: `athena/document/extractors/docx.py`
- Tool + OCR/vision dispatch: `athena/document/tools.py`
- OCR sibling: `docs/reference/ocr.md` (T4-06)
- Vision sibling: `docs/reference/vision-analyze.md` (T4-01)
- Audio sibling (also routes through media stack): `docs/reference/audio-analyze.md` (T4-04)
