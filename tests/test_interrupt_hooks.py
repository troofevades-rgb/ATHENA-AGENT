"""Cancel hooks for mid-stream interruption.

Pinning the contract that the agent's cancel hook actually fires
when the gateway dispatches an interrupt — and that buggy hooks
can't break sibling hooks. Without this wiring, ESC during a slow
LLM generation does nothing (``_thread.interrupt_main()`` queues
KeyboardInterrupt but the main thread is blocked in C code inside
``socket.recv`` and the signal doesn't deliver). Users saw this
as "ESC does nothing; I have to kill the terminal."
"""

from __future__ import annotations

import pytest

from athena import interrupt_hooks


@pytest.fixture(autouse=True)
def _reset():
    interrupt_hooks._reset_for_tests()
    yield
    interrupt_hooks._reset_for_tests()


def test_register_and_fire_calls_hook() -> None:
    fired: list[int] = []
    interrupt_hooks.register_cancel_hook(lambda: fired.append(1))
    interrupt_hooks.fire_cancel_hooks()
    assert fired == [1]


def test_register_is_idempotent_same_callable() -> None:
    """A double-register doesn't double-fire. Each registered
    callable is treated as a single hook."""
    fired: list[int] = []
    fn = lambda: fired.append(1)
    interrupt_hooks.register_cancel_hook(fn)
    interrupt_hooks.register_cancel_hook(fn)
    interrupt_hooks.fire_cancel_hooks()
    assert fired == [1]


def test_multiple_hooks_all_fire() -> None:
    fired: list[str] = []
    interrupt_hooks.register_cancel_hook(lambda: fired.append("a"))
    interrupt_hooks.register_cancel_hook(lambda: fired.append("b"))
    interrupt_hooks.register_cancel_hook(lambda: fired.append("c"))
    interrupt_hooks.fire_cancel_hooks()
    assert fired == ["a", "b", "c"]


def test_buggy_hook_does_not_block_others() -> None:
    """A hook that raises must not prevent sibling hooks from
    running. Critical: a single broken provider can't make ESC
    silently no-op for the whole session."""
    fired: list[str] = []

    def _good_before():
        fired.append("before")

    def _bad():
        raise RuntimeError("simulated cancel failure")

    def _good_after():
        fired.append("after")

    interrupt_hooks.register_cancel_hook(_good_before)
    interrupt_hooks.register_cancel_hook(_bad)
    interrupt_hooks.register_cancel_hook(_good_after)
    interrupt_hooks.fire_cancel_hooks()
    assert fired == ["before", "after"]


def test_unregister_removes_hook() -> None:
    fired: list[int] = []
    fn = lambda: fired.append(1)
    interrupt_hooks.register_cancel_hook(fn)
    interrupt_hooks.unregister_cancel_hook(fn)
    interrupt_hooks.fire_cancel_hooks()
    assert fired == []


def test_unregister_unknown_is_silent_noop() -> None:
    """Removing a hook that was never registered must NOT raise.
    Common during cleanup ordering races."""
    interrupt_hooks.unregister_cancel_hook(lambda: None)  # no exception


def test_no_hooks_fire_is_clean_noop() -> None:
    interrupt_hooks.fire_cancel_hooks()  # no exception


def test_thread_safe_concurrent_registration() -> None:
    """Many threads registering simultaneously must not corrupt
    the hook list."""
    import threading
    barrier = threading.Barrier(8)

    def _worker(i: int) -> None:
        barrier.wait()
        interrupt_hooks.register_cancel_hook(lambda i=i: None)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)
    # All 8 distinct lambdas registered without crashes
    interrupt_hooks.fire_cancel_hooks()  # also no crash on fire
