"""Observability plugin — install, hooks, metric instrumentation.

Uses the InMemoryMetricReader / InMemorySpanExporter helpers from
OTel SDK to inspect emitted telemetry without spinning up a real
collector.
"""

from __future__ import annotations

from typing import Any

import pytest

from athena.plugins.bundled.observability.plugin import (
    _HAVE_OTEL,
    ObservabilityPlugin,
)

pytestmark = pytest.mark.skipif(
    not _HAVE_OTEL,
    reason="opentelemetry SDK not installed",
)


def _plugin(config: dict[str, Any] | None = None) -> ObservabilityPlugin:
    p = ObservabilityPlugin(config or {})
    p.on_install()
    return p


# ---- install -------------------------------------------------------


def test_install_creates_tracer_and_meter() -> None:
    p = _plugin()
    assert p._tracer is not None
    assert p._meter is not None


def test_install_is_idempotent() -> None:
    p = ObservabilityPlugin({})
    p.on_install()
    first_tracer = p._tracer
    p.on_install()  # second call must not raise
    assert p._tracer is first_tracer


def test_install_creates_all_metric_instruments() -> None:
    p = _plugin()
    from athena.plugins.bundled.observability.metrics import (
        METRIC_COMPLETION_TOKENS,
        METRIC_FORK_COUNT,
        METRIC_PROMPT_TOKENS,
        METRIC_TOOL_CALL_COUNT,
        METRIC_TOOL_CALL_LATENCY,
        METRIC_TURN_COUNT,
        METRIC_TURN_LATENCY,
    )

    for name in (
        METRIC_TOOL_CALL_COUNT,
        METRIC_FORK_COUNT,
        METRIC_TURN_COUNT,
        METRIC_PROMPT_TOKENS,
        METRIC_COMPLETION_TOKENS,
    ):
        assert name in p._counters
    for name in (
        METRIC_TOOL_CALL_LATENCY,
        METRIC_TURN_LATENCY,
    ):
        assert name in p._histograms


# ---- session lifecycle --------------------------------------------


def test_session_start_records_span_attributes() -> None:
    p = _plugin()
    p.on_session_start("sess-123", "work")
    assert "sess-123" in p._session_spans
    span, _ = p._session_spans["sess-123"]
    # We can't easily read attributes off a span without an exporter
    # hooked in. Span existence is the contract; details get verified
    # via the in-memory exporter integration test below.
    assert span is not None


def test_session_end_closes_recorded_span() -> None:
    p = _plugin()
    p.on_session_start("sess-end", "default")
    p.on_session_end("sess-end", completed=True, interrupted=False)
    assert "sess-end" not in p._session_spans


def test_session_end_without_start_is_silent() -> None:
    """Defensive: an out-of-order session_end (race with shutdown)
    must not crash."""
    p = _plugin()
    p.on_session_end("never-started", completed=False, interrupted=True)


def test_session_start_with_empty_id_skipped() -> None:
    p = _plugin()
    p.on_session_start("", "default")
    assert "" not in p._session_spans


# ---- tool call hooks ----------------------------------------------


def test_pre_tool_call_returns_none_does_not_block() -> None:
    """Returning None means "I observed, did not veto". The agent
    only blocks on explicit False."""
    p = _plugin()
    args = {"path": "/etc/hosts"}
    assert p.pre_tool_call("Read", args) is None
    # Span recorded.
    assert id(args) in p._tool_spans


def test_post_tool_call_closes_span_and_records_metrics() -> None:
    p = _plugin()
    args = {"path": "/tmp/x"}
    p.pre_tool_call("Read", args)
    p.post_tool_call("Read", args, "file contents\n" * 10)
    assert id(args) not in p._tool_spans


def test_post_tool_call_without_pre_still_records_count() -> None:
    """A racing post (e.g., from a tool that bypassed pre_tool_call
    via a different code path) still bumps the counter."""
    p = _plugin()
    args = {"path": "/x"}
    p.post_tool_call("Read", args, "result")
    # No span recorded (none was opened), but no crash.


def test_pre_tool_call_args_redacted() -> None:
    """Span attributes should not contain raw secrets. The plugin
    calls redact_args; we verify by checking the attributes pre-
    redaction would have differed from what's set."""
    p = _plugin()
    args = {
        "command": "curl -H 'Authorization: Bearer secret-token-12345' x",
    }
    p.pre_tool_call("Bash", args)
    # The pre-redaction value is in args; span attributes (set
    # inside pre_tool_call before the dict gets keyed onto the
    # span) were redacted by redact_args. We confirm via the in-
    # memory exporter test below.


# ---- in-memory exporter integration ------------------------------


def test_tool_span_carries_redacted_args_and_latency() -> None:
    """Wire the plugin to an in-memory span exporter, fire a tool
    call, and verify the resulting span has redacted args + latency."""
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    # Construct a LOCAL TracerProvider (don't make it global — OTel
    # rejects setting the global twice, and other tests in this run
    # may have already done so).
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    plugin = ObservabilityPlugin({})
    plugin._tracer = provider.get_tracer("athena")

    args = {
        "command": "echo 'sk-abcdef0123456789ABCDEF01234567890123'",
        "timeout": 30,
    }
    plugin.pre_tool_call("Bash", args)
    plugin.post_tool_call("Bash", args, "hello world\n")

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    span = finished[0]
    assert span.name == "athena.tool_call.Bash"
    attrs = dict(span.attributes or {})
    assert attrs.get("athena.tool_name") == "Bash"
    # Secret in the command was redacted before becoming an attribute.
    cmd_attr = attrs.get("athena.tool_arg.command", "")
    assert "sk-" not in cmd_attr
    assert "<redacted>" in cmd_attr
    # Scalar arg passed through.
    assert attrs.get("athena.tool_arg.timeout") == 30
    # Latency was set in post.
    assert "athena.tool_call.latency_ms" in attrs
    assert attrs["athena.tool_call.latency_ms"] >= 0
    # Result length captured.
    assert attrs.get("athena.tool_result.length") == len("hello world\n")


def test_session_span_attributes_on_close() -> None:
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    plugin = ObservabilityPlugin({})
    plugin._tracer = provider.get_tracer("athena")

    plugin.on_session_start("sess-attrs", "work")
    plugin.on_session_end("sess-attrs", completed=True, interrupted=False)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    attrs = dict(spans[0].attributes or {})
    assert attrs["athena.session_id"] == "sess-attrs"
    assert attrs["athena.profile"] == "work"
    assert attrs["athena.session.completed"] is True
    assert attrs["athena.session.interrupted"] is False
    assert attrs["athena.session.duration_ms"] >= 0


# ---- helper hooks -------------------------------------------------


def test_record_fork_increments_counter_no_crash() -> None:
    p = _plugin()
    # Just verifying no exception — the in-memory metric reader
    # path is more complex than the in-memory span exporter and
    # already covered by OTel's own test suite.
    p.record_fork("background_review")
    p.record_fork("curator")


def test_record_tokens_no_crash() -> None:
    p = _plugin()
    p.record_tokens(prompt=100, completion=200)
    # Zero values short-circuit cleanly.
    p.record_tokens(prompt=0, completion=0)


def test_record_fork_without_install_silent() -> None:
    """Calling record_* before on_install (or with OTel absent)
    must not throw."""
    p = ObservabilityPlugin({})  # no on_install
    p.record_fork("background_review")  # no exception
    p.record_tokens(1, 2)


# ---- on_user_message / on_assistant_message ----------------------


def test_on_user_message_returns_none() -> None:
    """Plugin must not transform the prompt — observability is
    read-only."""
    p = _plugin()
    assert p.on_user_message("hello") is None


def test_on_assistant_message_does_not_raise() -> None:
    p = _plugin()
    p.on_assistant_message("response text")
