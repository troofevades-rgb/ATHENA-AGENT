"""0.3.0 observability -- turn + per-tool latency, error counters.

Stats grows three pieces of dogfood-grade observability:

  * ``turn_durations_ms`` -- rolling window of recent
    ``_run_turn_inner`` durations. ``/status`` renders count + p50 +
    p95 + p99 so the operator can spot model-side slowdowns
    ("p95 climbed from 4s to 14s after rebuild X").
  * ``tool_durations_ms`` -- same shape, keyed by tool name. Reveals
    the one slow tool (an MCP server that started timing out, a
    WebFetch hitting a degraded upstream) without an external
    profiler.
  * ``provider_errors`` / ``tool_errors`` -- counters wired into the
    streaming except block and the tool-dispatch except block. A
    non-zero count in ``/status`` is the "something is wrong"
    signal.

These pins lock the *contract*: shape of the rolling-window record
methods, bounded growth, percentile correctness, snapshot key
presence/absence, render output. Without them a future refactor
could silently swap to per-call lists with no maxlen and reintroduce
the unbounded-memory regression we're avoiding here.
"""

from __future__ import annotations

from athena.agent.stats import _LATENCY_WINDOW, Stats, _percentile

# ---------------------------------------------------------------------------
# Percentile helper -- nearest-rank, no interpolation
# ---------------------------------------------------------------------------


def test_percentile_empty_returns_zero() -> None:
    assert _percentile([], 50) == 0.0
    assert _percentile([], 99) == 0.0


def test_percentile_single_sample_is_that_sample() -> None:
    assert _percentile([42.0], 50) == 42.0
    assert _percentile([42.0], 99) == 42.0


def test_percentile_p50_is_median() -> None:
    # Nearest-rank p50 of 1..10 is the 5th sample (idx=5, value=6).
    samples = [float(x) for x in range(1, 11)]
    assert _percentile(samples, 50) == 6.0


def test_percentile_p99_is_max_for_small_n() -> None:
    samples = [1.0, 2.0, 3.0, 4.0, 100.0]
    assert _percentile(samples, 99) == 100.0


def test_percentile_p0_is_min_p100_is_max() -> None:
    samples = [5.0, 1.0, 9.0, 3.0]
    assert _percentile(samples, 0) == 1.0
    assert _percentile(samples, 100) == 9.0


# ---------------------------------------------------------------------------
# record_turn_duration / record_tool_duration -- bounded growth
# ---------------------------------------------------------------------------


def test_record_turn_duration_converts_to_ms() -> None:
    """Caller passes seconds; the rolling window stores ms so
    ``/status`` doesn't need to do the conversion."""
    stats = Stats()
    stats.record_turn_duration(0.250)  # 250ms
    stats.record_turn_duration(1.500)  # 1500ms
    assert list(stats.turn_durations_ms) == [250.0, 1500.0]


def test_record_tool_duration_lazy_creates_buckets() -> None:
    """A tool that's never been called must not pre-allocate a
    bucket -- ``tool_durations_ms`` should only contain keys for
    tools we've actually timed."""
    stats = Stats()
    assert stats.tool_durations_ms == {}
    stats.record_tool_duration("Read", 0.001)
    assert "Read" in stats.tool_durations_ms
    assert "Bash" not in stats.tool_durations_ms
    stats.record_tool_duration("Bash", 0.500)
    assert list(stats.tool_durations_ms["Read"]) == [1.0]
    assert list(stats.tool_durations_ms["Bash"]) == [500.0]


def test_turn_durations_window_is_bounded() -> None:
    """A long-running session must NOT accumulate unbounded
    samples -- deque(maxlen=_LATENCY_WINDOW) caps the memory.
    Without this pin a future refactor to ``list[]`` would let a
    24-hour gateway session OOM."""
    stats = Stats()
    # Push more samples than the window size.
    for i in range(_LATENCY_WINDOW + 100):
        stats.record_turn_duration(0.001 * i)
    assert len(stats.turn_durations_ms) == _LATENCY_WINDOW


def test_tool_durations_window_is_bounded_per_tool() -> None:
    """Each per-tool bucket is independently bounded -- a flood
    of Read calls doesn't push Bash samples out, and neither
    bucket exceeds the window cap."""
    stats = Stats()
    for i in range(_LATENCY_WINDOW + 50):
        stats.record_tool_duration("Read", 0.001 * i)
    stats.record_tool_duration("Bash", 0.5)
    assert len(stats.tool_durations_ms["Read"]) == _LATENCY_WINDOW
    assert len(stats.tool_durations_ms["Bash"]) == 1


# ---------------------------------------------------------------------------
# Error counters
# ---------------------------------------------------------------------------


def test_provider_and_tool_errors_default_zero() -> None:
    stats = Stats()
    assert stats.provider_errors == 0
    assert stats.tool_errors == 0


def test_record_provider_error_increments() -> None:
    stats = Stats()
    stats.record_provider_error()
    stats.record_provider_error()
    assert stats.provider_errors == 2


def test_record_tool_error_increments_independently() -> None:
    stats = Stats()
    stats.record_provider_error()
    stats.record_tool_error()
    assert stats.provider_errors == 1
    assert stats.tool_errors == 1


# ---------------------------------------------------------------------------
# to_snapshot -- observability fields appear (and are None / empty
# until populated)
# ---------------------------------------------------------------------------


def test_snapshot_omits_turn_latency_when_empty() -> None:
    """Fresh session, no turns yet -- the snapshot's
    ``turn_latency_ms`` must be None so ``/status`` knows to skip
    the latency block rather than render p50=0.0 noise."""
    snap = Stats().to_snapshot(
        session_id="s",
        model="m",
        provider="p",
        profile="prof",
    )
    assert snap["turn_latency_ms"] is None
    assert snap["tool_latencies_ms"] == {}


def test_snapshot_emits_turn_latency_when_populated() -> None:
    stats = Stats()
    for ms in [100.0, 200.0, 300.0, 400.0, 500.0]:
        stats.record_turn_duration(ms / 1000.0)
    snap = stats.to_snapshot(
        session_id="s",
        model="m",
        provider="p",
        profile="prof",
    )
    lat = snap["turn_latency_ms"]
    assert lat is not None
    assert lat["count"] == 5
    # p50 with nearest-rank of [100, 200, 300, 400, 500] -> idx 2 -> 300.
    assert lat["p50_ms"] == 300.0
    assert lat["p99_ms"] == 500.0


def test_snapshot_emits_per_tool_latencies() -> None:
    stats = Stats()
    stats.record_tool_duration("Read", 0.010)  # 10ms
    stats.record_tool_duration("Read", 0.020)  # 20ms
    stats.record_tool_duration("WebFetch", 0.800)  # 800ms
    snap = stats.to_snapshot(
        session_id="s",
        model="m",
        provider="p",
        profile="prof",
    )
    tl = snap["tool_latencies_ms"]
    assert set(tl.keys()) == {"Read", "WebFetch"}
    assert tl["Read"]["count"] == 2
    assert tl["WebFetch"]["count"] == 1
    assert tl["WebFetch"]["p50_ms"] == 800.0


def test_snapshot_carries_error_counters() -> None:
    stats = Stats()
    stats.record_provider_error()
    stats.record_provider_error()
    stats.record_tool_error()
    snap = stats.to_snapshot(
        session_id="s",
        model="m",
        provider="p",
        profile="prof",
    )
    assert snap["provider_errors"] == 2
    assert snap["tool_errors"] == 1


# ---------------------------------------------------------------------------
# render_status integrates the new fields
# ---------------------------------------------------------------------------


def test_render_status_skips_latency_block_on_empty_session() -> None:
    """A fresh session's /status must not show a latency block --
    the renderer is gated on ``turn_latency_ms is not None``."""
    from athena.cli.status import render_status

    snap = Stats().to_snapshot(
        session_id="s",
        model="m",
        provider="p",
        profile="prof",
    )
    out = render_status(snap)
    assert "turn latency" not in out
    assert "tool latency" not in out


def test_render_status_includes_turn_latency_when_present() -> None:
    from athena.cli.status import render_status

    stats = Stats()
    stats.record_turn_duration(1.250)  # 1250ms
    snap = stats.to_snapshot(
        session_id="s",
        model="m",
        provider="p",
        profile="prof",
    )
    out = render_status(snap)
    assert "turn latency" in out
    # Renderer prints integer ms; 1250 should appear somewhere.
    assert "1250" in out


def test_render_status_sorts_tools_by_p95_desc() -> None:
    """Slowest tool surfaces first -- the renderer sorts by p95
    descending so a quick glance highlights the worst offender."""
    from athena.cli.status import render_status

    stats = Stats()
    stats.record_tool_duration("FastTool", 0.005)
    stats.record_tool_duration("SlowTool", 5.000)
    stats.record_tool_duration("MediumTool", 0.500)
    snap = stats.to_snapshot(
        session_id="s",
        model="m",
        provider="p",
        profile="prof",
    )
    out = render_status(snap)
    # SlowTool's line precedes MediumTool's line precedes FastTool's.
    slow_idx = out.index("SlowTool")
    med_idx = out.index("MediumTool")
    fast_idx = out.index("FastTool")
    assert slow_idx < med_idx < fast_idx


def test_render_status_includes_error_counters_when_nonzero() -> None:
    from athena.cli.status import render_status

    stats = Stats()
    stats.record_provider_error()
    stats.record_tool_error()
    stats.record_tool_error()
    snap = stats.to_snapshot(
        session_id="s",
        model="m",
        provider="p",
        profile="prof",
    )
    out = render_status(snap)
    assert "errors" in out
    assert "provider=1" in out
    assert "tool=2" in out


def test_render_status_skips_error_line_when_all_zero() -> None:
    """No errors -- no error line. /status stays clean on a healthy
    session."""
    from athena.cli.status import render_status

    snap = Stats().to_snapshot(
        session_id="s",
        model="m",
        provider="p",
        profile="prof",
    )
    out = render_status(snap)
    assert "errors:" not in out
