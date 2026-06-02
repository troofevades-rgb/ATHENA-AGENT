"""non_foreground_thread: the shared thread-entry guard for
non-foreground tool-loop workers (fork / cron / webhooks / eval).

Pins the contract that one CM installs all three guards (write-origin,
AUTO_DENY, fresh approval scope) and unwinds them cleanly — replacing
four hand-rolled copies that had drifted.
"""

from __future__ import annotations

import threading

from athena import provenance
from athena.provenance import SYSTEM, get_current_write_origin
from athena.safety.approval_callback import AUTO_DENY, get_approval_callback
from athena.safety.approval_guard import current_grants
from athena.safety.thread_entry import non_foreground_thread


def test_installs_all_three_guards() -> None:
    with non_foreground_thread(origin=SYSTEM):
        assert get_current_write_origin() == SYSTEM
        cb = get_approval_callback()
        assert cb is AUTO_DENY
        assert cb("Bash", {"command": "rm -rf /"}) == "deny"
        assert current_grants() == {}


def test_restores_prior_state() -> None:
    before = get_current_write_origin()
    with non_foreground_thread(origin=SYSTEM):
        assert get_current_write_origin() == SYSTEM
    # Every guard unwinds to what it was before the block.
    assert get_current_write_origin() == before
    assert get_approval_callback() is not AUTO_DENY


def test_restores_nested_origin() -> None:
    tok = provenance.set_current_write_origin(provenance.CURATOR)
    try:
        with non_foreground_thread(origin=SYSTEM):
            assert get_current_write_origin() == SYSTEM
        assert get_current_write_origin() == provenance.CURATOR
    finally:
        provenance.reset_current_write_origin(tok)


def test_works_inside_worker_thread() -> None:
    """The real use case: entered inside a spawned thread, the guards
    take effect there (ContextVars don't cross the boundary, so the CM
    must be entered in-thread — this asserts it does its job there)."""
    seen: dict[str, object] = {}

    def _worker() -> None:
        with non_foreground_thread(origin=SYSTEM):
            seen["origin"] = get_current_write_origin()
            seen["cb"] = get_approval_callback()

    t = threading.Thread(target=_worker)
    t.start()
    t.join()
    assert seen["origin"] == SYSTEM
    assert seen["cb"] is AUTO_DENY
