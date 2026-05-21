"""Document analysis (T4-05).

`document_analyze` extracts structured content from digital
documents: clean text, a heading/section outline, tables, and
metadata. Per-page streaming so large documents don't load
everything at once. Scanned PDF pages (no text layer) route to
OCR (T4-06) when available; degrade cleanly to "no text + flag"
when not. Embedded figures can be described via vision_analyze
(T4-01) opt-in.

Adapters per format under ``athena/document/extractors/``;
library choices isolated to those files. The tool surface lives
in :mod:`athena.document.tools`.
"""

from __future__ import annotations
