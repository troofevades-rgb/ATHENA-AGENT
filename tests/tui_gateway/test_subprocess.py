"""End-to-end gateway↔Ink-bundle smoke tests.

Skipped automatically if ``node`` isn't on PATH or the built
bundle isn't present (this happens on fresh clones before
``cd ui-tui && bun run build``). Devs running the full TUI flow
will have both; CI gets ``bun run build`` as a setup step.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from athena.tui_gateway.events import (
    BannerEvent,
    ExitEvent,
    ToolSetSummary,
)
from athena.tui_gateway.server import TuiGateway, _locate_bundle


pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node not on PATH — TUI subprocess tests need Node 22+",
)


def _bundle_or_skip() -> Path:
    try:
        return _locate_bundle()
    except FileNotFoundError as e:
        pytest.skip(str(e))


def test_gateway_spawns_and_exits_cleanly():
    """Smoke — the bundle starts, accepts an exit event, and the
    process terminates within the timeout. If this hangs in CI the
    likely cause is a stdin/stdout buffering mismatch."""
    bundle = _bundle_or_skip()
    gateway = TuiGateway(bundle_path=bundle, tty_passthrough=False)
    gateway.start()
    try:
        # No interaction yet — just confirm the process is alive.
        time.sleep(0.3)
        assert gateway._proc is not None
        assert gateway._proc.poll() is None, "TUI died before exit event"
    finally:
        gateway.close(timeout_s=2.0)
    assert gateway._proc is not None
    assert gateway._proc.poll() is not None, "TUI didn't exit after ExitEvent"


def test_gateway_send_event_does_not_block():
    """A reasonable burst of events must not deadlock if the TUI
    is slow to consume — Phase 1.2 uses unbuffered stdin on the
    Python side, so back-pressure on the pipe shouldn't stall."""
    bundle = _bundle_or_skip()
    gateway = TuiGateway(bundle_path=bundle, tty_passthrough=False)
    gateway.start()
    try:
        time.sleep(0.2)
        for i in range(20):
            gateway.send_event(
                BannerEvent(
                    model=f"m-{i}",
                    cwd="/tmp",
                    theme="cyber",
                    tools=[ToolSetSummary(name="file", tools=["Read"])],
                )
            )
    finally:
        gateway.close(timeout_s=2.0)


def test_gateway_handles_exit_event_only():
    """The TUI must respect a bare ExitEvent — that's how we shut
    down cleanly on normal session end. If this regresses the
    user will see an orphaned node process after ``athena``."""
    bundle = _bundle_or_skip()
    gateway = TuiGateway(bundle_path=bundle, tty_passthrough=False)
    gateway.start()
    try:
        time.sleep(0.2)
        gateway.send_event(ExitEvent(reason="test"))
        # Give the TUI a moment to receive + render the event
        # before close() forces shutdown.
        time.sleep(0.5)
    finally:
        gateway.close(timeout_s=2.0)
    # Process should have exited via the event, not the kill path.
    assert gateway._proc is not None
    assert gateway._proc.returncode == 0
