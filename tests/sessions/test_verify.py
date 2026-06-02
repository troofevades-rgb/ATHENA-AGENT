"""SessionStore.verify() drift detector + `athena sessions verify` CLI,
plus a regression for the purge `store._db` bug fixed alongside it.
"""

from __future__ import annotations

import json
from pathlib import Path

from athena.cli import sessions as sessions_cli
from athena.sessions.store import SessionMeta, SessionStore, new_session_id


def _store(tmp_path: Path) -> SessionStore:
    # Mirror the CLI's layout: <home>/profiles/<profile>/.
    return SessionStore(tmp_path / "profiles" / "default")


def _make_session(store: SessionStore, n_turns: int) -> str:
    sid = new_session_id()
    store.open_session(SessionMeta(session_id=sid, profile="default", model="m"))
    for i in range(n_turns):
        store.append_turn(sid, {"role": "user", "content": f"msg {i}"})
    return sid


def test_verify_clean_store_all_ok(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        _make_session(store, 3)
        _make_session(store, 0)  # opened, no turns — still consistent
        rows = store.verify()
        assert rows, "expected at least the sessions we created"
        assert all(r.ok for r in rows)
        assert all(r.jsonl_turns == r.db_turns for r in rows)
    finally:
        store.close()


def test_verify_detects_jsonl_ahead_of_index(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        sid = _make_session(store, 2)
        # Append a raw line straight to the JSONL, bypassing the mirror —
        # simulates a crash between the JSONL write and the SQLite insert.
        jpath = store.sessions_dir / f"{sid}.jsonl"
        with open(jpath, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"role": "user", "content": "orphaned"}) + "\n")
        row = next(r for r in store.verify() if r.session_id == sid)
        assert not row.ok
        assert row.jsonl_turns == 3
        assert row.db_turns == 2
    finally:
        store.close()


def test_verify_detects_unindexed_jsonl(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        # A .jsonl file with no open_session() → no sessions-table row.
        orphan = store.sessions_dir / "019aaaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee.jsonl"
        orphan.write_text(json.dumps({"role": "user", "content": "x"}) + "\n", encoding="utf-8")
        row = next(r for r in store.verify() if r.session_id == orphan.stem)
        assert not row.ok
        assert row.indexed is False
    finally:
        store.close()


def test_cli_verify_exit_codes(tmp_path: Path) -> None:
    # Clean store → exit 0.
    store = _store(tmp_path)
    sid = _make_session(store, 2)
    store.close()
    rc = sessions_cli.main(["--home", str(tmp_path), "--profile", "default", "verify"])
    assert rc == 0

    # Induce drift → exit 1.
    store = _store(tmp_path)
    with open(store.sessions_dir / f"{sid}.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"role": "user", "content": "drift"}) + "\n")
    store.close()
    rc = sessions_cli.main(["--home", str(tmp_path), "--profile", "default", "verify"])
    assert rc == 1


def test_purge_does_not_crash_on_db_access(tmp_path: Path) -> None:
    """Regression: _cmd_purge used a nonexistent store._db attribute and
    would AttributeError mid-purge (after unlinking files). It must run
    cleanly and remove both the files and the index rows."""
    store = _store(tmp_path)
    sid = _make_session(store, 1)
    store.close()

    rc = sessions_cli.main(
        [
            "--home",
            str(tmp_path),
            "--profile",
            "default",
            "purge",
            "--before",
            "2999-01-01",
            "--confirm",
        ]
    )
    assert rc == 0

    store = _store(tmp_path)
    try:
        assert not (store.sessions_dir / f"{sid}.jsonl").exists()
        # No index rows left for the purged session.
        rows = [r for r in store.verify() if r.session_id == sid]
        assert rows == []
    finally:
        store.close()
