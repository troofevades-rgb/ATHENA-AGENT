"""Tests for ``/steer`` and ``/queue`` — in-flight redirect commands.

Both commands operate on the module-level ``GLOBAL_STEER_QUEUE``
singleton, so every test must clear the queue before/after to
avoid cross-test pollution.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from athena.commands.steer import cmd_queue, cmd_steer
from athena.steer.queue import GLOBAL_STEER_QUEUE


@pytest.fixture(autouse=True)
def _clean_queue():
    """Drop any pending steers before AND after each test so a
    leftover entry never bleeds into the next assertion."""
    for sid in list(GLOBAL_STEER_QUEUE._q.keys()):  # type: ignore[attr-defined]
        GLOBAL_STEER_QUEUE.clear(sid)
    yield
    for sid in list(GLOBAL_STEER_QUEUE._q.keys()):  # type: ignore[attr-defined]
        GLOBAL_STEER_QUEUE.clear(sid)


def _capture_ui(module_path: str):
    lines: list[str] = []
    patches = []
    for fn_name in ("info", "warn", "error"):
        patches.append(
            patch(
                f"{module_path}.ui.{fn_name}",
                side_effect=lambda msg, *a, _n=fn_name, **kw:
                    lines.append(f"{_n}: {msg}"),
            )
        )
    patches.append(
        patch(
            f"{module_path}.ui.console.print",
            side_effect=lambda *a, **kw:
                lines.append(" ".join(str(x) for x in a)),
        )
    )
    return lines, patches


def _run(cmd_fn, agent, arg: str) -> str:
    lines, patches = _capture_ui("athena.commands.steer")
    for p in patches:
        p.start()
    try:
        cmd_fn(agent, arg)
    finally:
        for p in patches:
            p.stop()
    return "\n".join(lines)


def _agent(session_id: str | None = "test-sess"):
    return SimpleNamespace(session_id=session_id)


# ---- /steer ---------------------------------------------------------


def test_steer_no_arg_prints_usage() -> None:
    out = _run(cmd_steer, _agent(), "")
    assert "usage" in out.lower()
    assert "/steer" in out


def test_steer_push_adds_message_to_queue() -> None:
    agent = _agent("s1")
    out = _run(cmd_steer, agent, "review the diff before committing")
    pending = GLOBAL_STEER_QUEUE.list("s1")
    assert pending == ["review the diff before committing"]
    assert "queued" in out.lower()
    assert "1 pending" in out


def test_steer_multiple_pushes_accumulate_in_order() -> None:
    agent = _agent("s2")
    _run(cmd_steer, agent, "first")
    _run(cmd_steer, agent, "second")
    out = _run(cmd_steer, agent, "third")
    pending = GLOBAL_STEER_QUEUE.list("s2")
    assert pending == ["first", "second", "third"]
    assert "3 pending" in out


def test_steer_per_session_isolation() -> None:
    """Steers for one session must not show up in another's queue."""
    _run(cmd_steer, _agent("alpha"), "alpha-msg")
    _run(cmd_steer, _agent("beta"), "beta-msg")
    assert GLOBAL_STEER_QUEUE.list("alpha") == ["alpha-msg"]
    assert GLOBAL_STEER_QUEUE.list("beta") == ["beta-msg"]


def test_steer_clear_empties_queue() -> None:
    agent = _agent("s3")
    _run(cmd_steer, agent, "one")
    _run(cmd_steer, agent, "two")
    assert len(GLOBAL_STEER_QUEUE.list("s3")) == 2
    out = _run(cmd_steer, agent, "clear")
    assert GLOBAL_STEER_QUEUE.list("s3") == []
    assert "cleared 2" in out


def test_steer_clear_with_empty_queue_reports_zero() -> None:
    out = _run(cmd_steer, _agent("empty"), "clear")
    assert "cleared 0" in out


def test_steer_no_session_id_falls_back_to_sentinel() -> None:
    """When agent.session_id is None (e.g. plan mode), the queue
    must still accept the steer rather than crashing."""
    agent = _agent(session_id=None)
    out = _run(cmd_steer, agent, "still works")
    assert "queued" in out.lower()
    # The sentinel session key holds it
    assert GLOBAL_STEER_QUEUE.list("_no_session") == ["still works"]


# ---- /queue ---------------------------------------------------------


def test_queue_empty_message() -> None:
    out = _run(cmd_queue, _agent("empty"), "")
    assert "no pending" in out.lower()


def test_queue_lists_pending_with_numbers() -> None:
    agent = _agent("q1")
    _run(cmd_steer, agent, "alpha")
    _run(cmd_steer, agent, "beta")
    _run(cmd_steer, agent, "gamma")
    out = _run(cmd_queue, agent, "")
    # All three messages appear
    assert "alpha" in out
    assert "beta" in out
    assert "gamma" in out
    # Numbered 1, 2, 3
    assert "1. alpha" in out
    assert "2. beta" in out
    assert "3. gamma" in out


def test_queue_does_not_consume_steers() -> None:
    """``/queue`` is read-only — listing must not empty the queue."""
    agent = _agent("q2")
    _run(cmd_steer, agent, "keep me")
    _run(cmd_queue, agent, "")
    assert GLOBAL_STEER_QUEUE.list("q2") == ["keep me"]
