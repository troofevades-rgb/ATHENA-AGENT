"""Observability plugin.

Wires OpenTelemetry tracing + metrics + JSON structured logging
into the agent's lifecycle hooks. Disabled by default — activate
with::

    athena plugins enable observability

Hooks:

- ``on_install``: idempotently set up the tracer / meter providers
  and the JSON log handler. Re-running it (toggling the plugin) is
  safe.
- ``on_session_start`` / ``on_session_end``: bracket the session
  with a long-running span (``athena.session``) so child spans
  (turns, tool calls) nest correctly.
- ``pre_tool_call`` / ``post_tool_call``: a span per tool call,
  arguments redacted via :mod:`.redaction`. Metrics: count +
  latency histogram, tagged with ``tool_name``.
- ``on_user_message`` / ``on_assistant_message``: no-op pass-throughs
  that increment the turn counter.

If the optional ``[observability]`` extras aren't installed, every
OTel call no-ops via :mod:`.spans` — the plugin still loads but
emits nothing. The JSON-logging install requires ``python-json-
logger``; absent the dep, we fall back to keeping the default
formatter and log a single warning.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from athena.plugins.base import Plugin

from .metrics import (
    METRIC_COMPLETION_TOKENS,
    METRIC_FORK_COUNT,
    METRIC_PROMPT_TOKENS,
    METRIC_TOOL_CALL_COUNT,
    METRIC_TOOL_CALL_LATENCY,
    METRIC_TURN_COUNT,
    METRIC_TURN_LATENCY,
)
from .redaction import redact_args

logger = logging.getLogger("athena.observability")


# Optional-dep imports. The plugin loads with or without the
# ``[observability]`` extras installed; methods short-circuit when
# the OTel SDK isn't available.
try:
    from opentelemetry import metrics as _otel_metrics
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import (
        ConsoleMetricExporter,
        PeriodicExportingMetricReader,
    )
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )

    _HAVE_OTEL = True
except ImportError:  # pragma: no cover
    _otel_trace = None  # type: ignore[assignment]
    _otel_metrics = None  # type: ignore[assignment]
    _HAVE_OTEL = False


# PROCESS-level setup state. OTel's TracerProvider/MeterProvider are
# process globals (``set_tracer_provider`` ignores all but the first
# call), and each ``TracerProvider`` spins up a ``BatchSpanProcessor``
# daemon thread. Plugin instances are per-AGENT (Agent.__init__ loads
# its own plugins), so the gateway makes a new instance per session —
# without a process guard, every session would build a fresh provider
# and leak a thread. Build the providers + instruments ONCE here; every
# instance adopts the shared handles.
_PROCESS_LOCK = threading.Lock()
_PROCESS_SETUP: dict[str, Any] = {
    "done": False,
    "tracer": None,
    "meter": None,
    "counters": {},
    "histograms": {},
    "log_handler": None,
}


def _reset_process_setup_for_tests() -> None:
    """Test-only: clear the process-once cache so each test can drive a
    fresh setup. NOT used in production."""
    with _PROCESS_LOCK:
        _PROCESS_SETUP.update(
            done=False, tracer=None, meter=None, counters={}, histograms={}, log_handler=None
        )


class ObservabilityPlugin(Plugin):
    """Bundled observability plugin. Lazy on OTel imports."""

    name = "observability"
    version = "0.1.0"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._tracer: Any = None
        self._meter: Any = None
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}
        # session_id -> (span, start_monotonic) for the session-level span.
        self._session_spans: dict[str, tuple[Any, float]] = {}
        # In-flight tool-call span, stored per-thread. Each parallel
        # tool worker runs at most one tool at a time (the agent's
        # _handle_tool_call is sequential within a worker), so a
        # thread-local "current span" is sufficient correlation
        # without leaking memory.
        #
        # Pre-fix this was ``dict[int, tuple]`` keyed on
        # ``id(tool_args)``. The agent's plugin dispatcher copies the
        # args dict via ``dict(tool_args)`` separately for the pre
        # and post hooks (see athena/plugins/hooks.py), so the two
        # ``id()`` values NEVER matched -- every tool call leaked an
        # entry in the dict, no tool span ever closed, latencies
        # were silently dropped, and OTel span buffers grew
        # unbounded. The leak was deterministic in any session that
        # made even one tool call.
        self._local = threading.local()
        self._log_handler: logging.Handler | None = None
        self._installed = False

    # ---- install / activation ----

    def on_install(self) -> None:
        """First-install hook. Setup is per-PROCESS, not once-ever, so
        the real work lives in :meth:`_ensure_setup` (also called from
        ``on_session_start``). The loader fires ``on_install`` only once
        per plugin name across the machine's lifetime — relying on it
        for tracer/meter/log setup meant the plugin emitted nothing from
        the SECOND session onward (every hook short-circuited on
        ``_tracer is None``). Now setup runs on the first session of
        every process."""
        self._ensure_setup()

    def _ensure_setup(self) -> None:
        """Bind this instance to the process-wide observability setup,
        building it on the first call in the process. Subsequent plugin
        instances (one per Agent) adopt the shared providers/instruments
        instead of constructing their own — which would leak an OTel
        BatchSpanProcessor thread per session and silently shadow the
        first instance's exporter config."""
        if self._installed:
            return
        with _PROCESS_LOCK:
            if not _PROCESS_SETUP["done"]:
                self._setup_logging()
                if _HAVE_OTEL:
                    self._setup_tracing()
                    self._setup_metrics()
                    self._build_instruments()
                else:
                    logger.warning(
                        "OpenTelemetry SDK not installed; spans/metrics disabled. "
                        'Install with: pip install -e ".[observability]"'
                    )
                _PROCESS_SETUP.update(
                    done=True,
                    tracer=self._tracer,
                    meter=self._meter,
                    counters=self._counters,
                    histograms=self._histograms,
                    log_handler=self._log_handler,
                )
            else:
                # Adopt the process-global handles built by the first
                # instance — no new provider, no new thread.
                self._tracer = _PROCESS_SETUP["tracer"]
                self._meter = _PROCESS_SETUP["meter"]
                self._counters = _PROCESS_SETUP["counters"]
                self._histograms = _PROCESS_SETUP["histograms"]
                self._log_handler = _PROCESS_SETUP["log_handler"]
        self._installed = True

    def _setup_logging(self) -> None:
        try:
            from .logging_config import install_json_logging
        except ImportError:  # pragma: no cover
            logger.warning("python-json-logger not installed; JSON logging disabled")
            return
        try:
            self._log_handler = install_json_logging(
                level=self.config.get("log_level", "INFO"),
                static_fields={
                    "service": str(self.config.get("service_name", "athena")),
                },
            )
        except Exception:  # pragma: no cover
            logger.exception("failed to install JSON logging")

    def _setup_tracing(self) -> None:
        if not _HAVE_OTEL:
            return
        resource = Resource.create(
            {
                "service.name": str(self.config.get("service_name", "athena")),
                "service.version": "0.2.0",
            }
        )
        provider = TracerProvider(resource=resource)
        exporter = self._build_span_exporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _otel_trace.set_tracer_provider(provider)
        self._tracer = _otel_trace.get_tracer("athena")

    def _build_span_exporter(self) -> Any:
        endpoint = self.config.get("otlp_endpoint")
        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                return OTLPSpanExporter(endpoint=str(endpoint))
            except ImportError:  # pragma: no cover
                logger.warning("OTLP exporter not installed; falling back to stderr")
        return ConsoleSpanExporter()

    def _setup_metrics(self) -> None:
        if not _HAVE_OTEL:
            return
        # Reader selection:
        #   - explicit OTLP endpoint    → periodic export to that endpoint
        #   - metrics_console=true      → periodic export to stdout
        #   - default (neither set)     → InMemoryMetricReader: meters
        #     still exist and accept calls, no background thread, no
        #     terminal spam, no teardown race
        #
        # The old default was to install ``ConsoleMetricExporter`` with
        # a 30s periodic reader unconditionally, which spammed the
        # terminal with metric dumps AND raced with stdout closure on
        # process exit (``ValueError: I/O operation on closed file``
        # during pytest teardown and every clean shutdown). The
        # in-memory reader keeps the meter API working for downstream
        # callers without either of those costs.
        endpoint = self.config.get("otlp_endpoint")
        console_opt_in = bool(self.config.get("metrics_console", False))
        reader: Any
        exporter: Any
        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                    OTLPMetricExporter,
                )

                exporter = OTLPMetricExporter(endpoint=str(endpoint))
            except ImportError:  # pragma: no cover
                exporter = ConsoleMetricExporter()
            reader = PeriodicExportingMetricReader(
                exporter,
                export_interval_millis=int(
                    self.config.get("metric_export_interval_ms", 30_000),
                ),
            )
        elif console_opt_in:
            reader = PeriodicExportingMetricReader(
                ConsoleMetricExporter(),
                export_interval_millis=int(
                    self.config.get("metric_export_interval_ms", 30_000),
                ),
            )
        else:
            from opentelemetry.sdk.metrics.export import InMemoryMetricReader

            reader = InMemoryMetricReader()
        provider = MeterProvider(metric_readers=[reader])
        _otel_metrics.set_meter_provider(provider)
        self._meter = _otel_metrics.get_meter("athena")

    def _build_instruments(self) -> None:
        """Cache metric handles so hot-path callers don't repeat the
        attribute lookups."""
        if self._meter is None:
            return
        self._counters[METRIC_TOOL_CALL_COUNT] = self._meter.create_counter(
            METRIC_TOOL_CALL_COUNT,
            description="Tool call count",
        )
        self._counters[METRIC_FORK_COUNT] = self._meter.create_counter(
            METRIC_FORK_COUNT,
            description="Agent fork count",
        )
        self._counters[METRIC_TURN_COUNT] = self._meter.create_counter(
            METRIC_TURN_COUNT,
            description="User turn count",
        )
        self._counters[METRIC_PROMPT_TOKENS] = self._meter.create_counter(
            METRIC_PROMPT_TOKENS,
            description="Prompt tokens consumed",
        )
        self._counters[METRIC_COMPLETION_TOKENS] = self._meter.create_counter(
            METRIC_COMPLETION_TOKENS,
            description="Completion tokens emitted",
        )
        self._histograms[METRIC_TOOL_CALL_LATENCY] = self._meter.create_histogram(
            METRIC_TOOL_CALL_LATENCY,
            description="Tool call latency in ms",
            unit="ms",
        )
        self._histograms[METRIC_TURN_LATENCY] = self._meter.create_histogram(
            METRIC_TURN_LATENCY,
            description="User turn latency in ms",
            unit="ms",
        )

    # ---- session lifecycle ----

    def on_session_start(self, session_id: str, profile: str) -> None:
        # Per-process lazy setup: the loader calls on_install only once
        # per name EVER, so a second-or-later process would otherwise
        # have no tracer/meter at all.
        self._ensure_setup()
        if self._tracer is None or not session_id:
            return
        try:
            span = self._tracer.start_span(
                "athena.session",
                attributes={
                    "athena.session_id": session_id,
                    "athena.profile": profile,
                },
            )
            self._session_spans[session_id] = (span, time.monotonic())
        except Exception:
            logger.debug("session span start failed", exc_info=True)

    def on_session_end(
        self,
        session_id: str,
        completed: bool,
        interrupted: bool,
    ) -> None:
        entry = self._session_spans.pop(session_id, None)
        if entry is None:
            return
        span, started = entry
        try:
            span.set_attribute("athena.session.completed", completed)
            span.set_attribute("athena.session.interrupted", interrupted)
            span.set_attribute(
                "athena.session.duration_ms",
                (time.monotonic() - started) * 1000.0,
            )
            span.end()
        except Exception:
            logger.debug("session span end failed", exc_info=True)

    # ---- tool dispatch ----

    def pre_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> bool | None:
        # Plugins on the bus return None to indicate "I observed, did
        # not block". The tool veto path checks for False explicitly.
        if self._tracer is None:
            return None
        try:
            attrs = {"athena.tool_name": tool_name, **redact_args(tool_args)}
            span = self._tracer.start_span(
                f"athena.tool_call.{tool_name}",
                attributes=attrs,
            )
        except Exception:
            logger.debug("tool span start failed", exc_info=True)
            return None
        # Stash the (span, started_at, tool_name) on the current
        # thread-local. Each parallel tool worker runs at most one
        # tool at a time, so a single per-thread slot is the right
        # correlation primitive between pre and post. (See the
        # ``_local`` field's docstring for the bug this replaces.)
        #
        # If a prior pre fired but its post never did (e.g., another
        # plugin vetoed the tool between the pre and post hooks --
        # the dispatcher returns before post in that case), the
        # previous span is overwritten here; its OTel span object
        # never gets .end()'d. That's a bounded leak (one per
        # vetoed call per worker) rather than the unbounded leak
        # the previous id()-based correlation produced on every
        # successful call.
        self._local.current = (span, time.monotonic(), tool_name)
        return None

    def post_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: str,
    ) -> None:
        entry = getattr(self._local, "current", None)
        latency_ms: float | None = None
        if entry is not None:
            span, started, pre_name = entry
            # Clear the slot before doing any span work so a re-entrancy
            # / exception path can't double-emit the same span.
            self._local.current = None
            # Defensive: if names don't match, the dispatcher state is
            # inconsistent (a parallel-worker pre/post mismatch). Drop
            # the span without recording rather than emit a wrong-tool
            # latency.
            if pre_name != tool_name:
                logger.debug(
                    "tool span name mismatch: pre=%s post=%s; dropping span",
                    pre_name,
                    tool_name,
                )
                entry = None
        if entry is not None:
            latency_ms = (time.monotonic() - started) * 1000.0
            try:
                span.set_attribute(
                    "athena.tool_result.length",
                    len(result) if isinstance(result, str) else 0,
                )
                span.set_attribute(
                    "athena.tool_call.latency_ms",
                    latency_ms,
                )
                span.end()
            except Exception:
                logger.debug("tool span end failed", exc_info=True)

        # Metrics fire regardless of whether the span hook
        # succeeded; they're keyed on tool_name so a missing pre-call
        # span (race / re-entrancy) doesn't lose the count.
        counter = self._counters.get(METRIC_TOOL_CALL_COUNT)
        if counter is not None:
            try:
                counter.add(1, {"athena.tool_name": tool_name})
            except Exception:
                logger.debug("tool counter add failed", exc_info=True)
        histogram = self._histograms.get(METRIC_TOOL_CALL_LATENCY)
        if histogram is not None and latency_ms is not None:
            try:
                histogram.record(
                    latency_ms,
                    {"athena.tool_name": tool_name},
                )
            except Exception:
                logger.debug("tool latency record failed", exc_info=True)

    # ---- message hooks ----

    def on_user_message(self, prompt: str) -> str | None:
        # No transformation; the counter increment lives in
        # on_assistant_message because that's when we know a turn
        # actually completed (interrupted turns don't count as
        # observed throughput).
        return None

    def on_assistant_message(self, content: str) -> None:
        counter = self._counters.get(METRIC_TURN_COUNT)
        if counter is not None:
            try:
                counter.add(1)
            except Exception:
                logger.debug("turn counter add failed", exc_info=True)

    # ---- public helpers for stats integration -------------------

    def record_fork(self, kind: str) -> None:
        """Called by the fork primitive (Phase 3) — when wired in
        Phase 16.2's StatsAccumulator integration. ``kind`` is
        ``"background_review"`` / ``"curator"`` / ``"sub_agent"``."""
        counter = self._counters.get(METRIC_FORK_COUNT)
        if counter is None:
            return
        try:
            counter.add(1, {"athena.fork.kind": kind})
        except Exception:
            logger.debug("fork counter add failed", exc_info=True)

    def record_tokens(self, prompt: int, completion: int) -> None:
        """Called once per turn from the agent's stream-end path.
        Cheap no-op when OTel isn't installed."""
        p = self._counters.get(METRIC_PROMPT_TOKENS)
        c = self._counters.get(METRIC_COMPLETION_TOKENS)
        if p is not None and prompt:
            try:
                p.add(int(prompt))
            except Exception:
                logger.debug("prompt token add failed", exc_info=True)
        if c is not None and completion:
            try:
                c.add(int(completion))
            except Exception:
                logger.debug("completion token add failed", exc_info=True)
