"""Span helpers — tiny wrappers that no-op when OTel isn't installed.

Plugin code uses :func:`start_span` instead of importing
opentelemetry directly so a profile running without the
``[observability]`` extras (no OTel SDK) still works — the helpers
become inert and produce no spans.

This keeps the agent's tool-call wrappers (which want to call
:func:`start_span` regardless of whether observability is enabled)
from blowing up at import time when the optional dep is missing.
"""

from __future__ import annotations

import contextlib
from typing import Any

try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.trace import Span

    _HAVE_OTEL = True
except ImportError:  # pragma: no cover — exercised only without the extras
    _otel_trace = None
    Span = None  # type: ignore[misc,assignment]
    _HAVE_OTEL = False


@contextlib.contextmanager
def start_span(name: str, attributes: dict[str, Any] | None = None):
    """Context manager that yields a Span (or None when OTel is
    absent).

    Usage::

        with start_span("athena.tool_call", {"tool_name": name}) as span:
            ...  # span may be None; downstream code should handle both

    The wrapper avoids ``from opentelemetry import trace`` at every
    use-site and keeps optional-dep handling in one place.
    """
    if not _HAVE_OTEL or _otel_trace is None:
        yield None
        return
    tracer = _otel_trace.get_tracer("athena")
    with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
        yield span


def get_tracer():
    """Return the athena tracer (or ``None`` when OTel is absent).

    Callers usually want :func:`start_span` instead; this is here
    for the few code paths that need a tracer reference for manual
    span lifecycle management (``start_span`` + ``end()``).
    """
    if not _HAVE_OTEL or _otel_trace is None:
        return None
    return _otel_trace.get_tracer("athena")
