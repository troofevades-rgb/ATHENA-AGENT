"""ui.muted(): thread-local suppression of info/warn chatter.

Used by Agent.fork() to silence a child agent's construction-time
startup messages without affecting the parent thread. The
thread-locality is the load-bearing property — a module-global mute
would swallow the main thread's legitimate output while a background
fork is being constructed.
"""

from __future__ import annotations

import threading

from athena import ui


def _capture(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(ui.console, "print", lambda msg, *a, **k: calls.append(("print", msg)))
    # Ensure no gateway short-circuits the console path.
    monkeypatch.setattr(ui, "_active_gateway", None)
    return calls


def test_muted_suppresses_info_and_warn(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    with ui.muted():
        ui.info("boot chatter")
        ui.warn("boot warning")
    assert calls == []  # nothing printed while muted


def test_unmuted_emits_normally(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    ui.info("visible")
    assert len(calls) == 1


def test_mute_restores_previous_state(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    with ui.muted():
        ui.info("hidden")
    ui.info("visible again")
    assert len(calls) == 1  # only the post-block call landed


def test_errors_are_never_muted(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    with ui.muted():
        ui.error("this matters")
    # error() goes through _emit_message->console.print (no gateway).
    assert any("this matters" in c[1] for c in calls)


def test_mute_is_thread_local(monkeypatch) -> None:
    """Muting the spawning thread must NOT mute another thread — the
    exact property fork() relies on to avoid swallowing the parent's
    concurrent output during child construction."""
    calls = _capture(monkeypatch)
    other_emitted = threading.Event()

    def _other() -> None:
        # This thread never enters muted(); its info must print even
        # while the main thread is inside a muted() block.
        ui.info("from other thread")
        other_emitted.set()

    with ui.muted():
        ui.info("from muted main")  # suppressed
        t = threading.Thread(target=_other)
        t.start()
        t.join()

    assert other_emitted.is_set()
    printed = [c[1] for c in calls]
    assert any("from other thread" in m for m in printed)
    assert not any("from muted main" in m for m in printed)
