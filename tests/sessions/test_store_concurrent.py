"""SessionStore concurrent-writers regression test.

The gateway stress harness surfaced ``SystemError: error return
without exception set`` and ``Cannot operate on a closed database``
when many threads shared one ``sqlite3.Connection`` opened with
``check_same_thread=False``. The fix moved to one connection per
thread (lazily created on first access, all tracked for shutdown).
This test pins the behavior: 50 concurrent writer threads each
appending many turns to the same store finish cleanly, the on-disk
row count matches the number of writes, and ``close()`` shuts down
every thread's connection.
"""
from __future__ import annotations

import concurrent.futures
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from athena.sessions.store import SessionMeta, SessionStore


def _make_meta(session_id: str) -> SessionMeta:
    return SessionMeta(
        session_id=session_id,
        profile="default",
        model="stub",
        provider="stub",
        workspace="/tmp",
        parent_session_id=None,
        started_at=datetime.now(timezone.utc),
        ended_at=None,
        tags=[],
    )


def test_each_thread_gets_its_own_connection(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    seen_connection_ids: set[int] = set()
    lock = threading.Lock()

    def grab_conn() -> None:
        conn = store._conn()
        with lock:
            seen_connection_ids.add(id(conn))

    threads = [threading.Thread(target=grab_conn) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Different threads see different sqlite3.Connection instances.
    assert len(seen_connection_ids) == 8


def test_repeated_calls_in_one_thread_reuse_connection(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    a = store._conn()
    b = store._conn()
    assert a is b


def test_concurrent_append_turn_does_not_corrupt(tmp_path: Path) -> None:
    """50 threads, each appending 20 turns to its own session. Zero
    errors, every turn lands in sqlite, and the on-disk file is
    intact when we read it back."""
    store = SessionStore(tmp_path)
    n_threads = 50
    n_turns_per = 20

    session_ids = [f"sess-{i:03d}" for i in range(n_threads)]
    for sid in session_ids:
        store.open_session(_make_meta(sid))

    errors: list[BaseException] = []
    err_lock = threading.Lock()

    def worker(sid: str) -> None:
        try:
            for k in range(n_turns_per):
                store.append_turn(sid, {
                    "role": "user" if k % 2 == 0 else "assistant",
                    "content": f"turn {k} of {sid}",
                })
        except BaseException as e:
            with err_lock:
                errors.append(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as ex:
        list(ex.map(worker, session_ids))

    assert errors == []

    # Every turn made it into sqlite. Use a fresh connection because
    # the writer threads each have their own.
    fresh = sqlite3.connect(str(store.db_path))
    try:
        rows = fresh.execute(
            "SELECT COUNT(*) FROM turns"
        ).fetchone()
    finally:
        fresh.close()
    assert rows[0] == n_threads * n_turns_per


def test_close_shuts_down_every_thread_connection(tmp_path: Path) -> None:
    """Open connections on multiple threads, then close. Every one
    of them should be unusable afterwards."""
    store = SessionStore(tmp_path)
    captured: list[sqlite3.Connection] = []
    cap_lock = threading.Lock()

    def open_and_capture() -> None:
        c = store._conn()
        with cap_lock:
            captured.append(c)

    threads = [threading.Thread(target=open_and_capture) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(captured) == 4

    store.close()

    # Every captured connection raises ProgrammingError on use.
    for c in captured:
        try:
            c.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            continue
        raise AssertionError("connection survived store.close()")


def test_use_after_close_raises_runtime_error(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.close()
    try:
        store._conn()
    except RuntimeError as e:
        assert "closed" in str(e).lower()
        return
    raise AssertionError("_conn() did not raise after close")


def test_wal_mode_active(tmp_path: Path) -> None:
    """Per-thread connections enable WAL so concurrent readers don't
    block on writers. Check that the journal_mode pragma stuck."""
    store = SessionStore(tmp_path)
    row = store._conn().execute("PRAGMA journal_mode").fetchone()
    assert row[0].lower() == "wal"
