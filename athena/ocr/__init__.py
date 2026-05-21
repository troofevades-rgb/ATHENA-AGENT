"""OCR — text from images and scanned pages (T4-06).

`ocr(path)` reads text out of an image / rasterized page,
returning normalized blocks with bounding boxes + per-block
confidence. The broker routes to providers declaring the
``ocr`` capability via :class:`athena.media.registry.MediaRegistry`;
local-preferred by default so text-in-images never leaves the
machine.

Fills the OCR non-goal T4-01 vision explicitly declared:

  - **vision** describes an image — "this is a kitchen with a
    cat on the counter"
  - **OCR** reads the text IN an image — "the sign on the
    fridge says 'BREAD'"

The two are different jobs and route through different
backends. Consumed by:
  - T4-05 document_analyze for scanned PDF pages (no text
    layer → rasterize → ocr → merge)
  - T4-01 vision_analyze (or any future tool) when "what does
    the text in this image say" is the question
"""

from __future__ import annotations
