"""Video-generation backend adapters (T6-05.2).

Each adapter implements
:class:`athena.videogen.job.VideoGenerationBackend` and is
registered as a Provider declaring the ``video_generation``
capability so the T5-05 media broker can resolve it via
``MediaRegistry.backend_for("video_generation")``.

Vendor specifics (model names, API URLs, JSON shapes) live in
each adapter module and NOWHERE else — a vendor change is a
one-file edit.

The :mod:`stub_local` backend is intentionally a synthetic
local-only adapter that writes a tiny placeholder file. It
exists so:

  1. The broker has *something* declaring video_generation by
     default (so :func:`MediaRegistry.backend_for` returns a
     value rather than None when computer_use_enabled).
  2. CI / first-run smoke can exercise the full pipeline
     end-to-end without a hosted vendor key.

Real cloud / local model adapters land alongside it as
``runwayml.py`` / ``pika.py`` / ``ollama_video.py`` etc. when
those are wired at build time.
"""
