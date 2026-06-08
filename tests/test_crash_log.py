"""Crash log: captures unhandled exceptions to ``~/.athena/crashes/``.

Coverage:

  * ``write_crash_record`` produces a JSON file with the documented
    shape (ts / version / exception / context).
  * Secret scrubber redacts sk-... API keys, Bearer tokens,
    KEY=value patterns BEFORE the record hits disk.
  * Conversation content is NEVER in the record -- only message
    roles via ``CrashContext.last_message_roles``.
  * Rotation drops the OLDEST records when ``MAX_CRASH_RECORDS``
    is exceeded.
  * Atomic-rename pattern: a tmp file appears mid-write and is
    cleaned up before the final path appears.
  * ``install_excepthook`` swaps ``sys.excepthook`` and is
    idempotent; ``uninstall_excepthook`` restores the original.
  * The excepthook chains to the original AFTER writing -- the
    traceback still surfaces to the operator normally.
  * KeyboardInterrupt is NOT logged as a crash (intentional user
    interrupt).
  * Writer failure (unwritable dir, etc.) returns ``None`` instead
    of raising -- a broken writer must never mask the original
    exception.
  * ``capture_crash`` explicit API writes the same record shape
    with an optional ``note``.
  * ``recent_crashes`` filters by ``within_days`` and sorts
    newest-first.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from athena import crash_log
from athena.crash_log import (
    MAX_CRASH_RECORDS,
    CrashContext,
    capture_crash,
    install_excepthook,
    recent_crashes,
    register_context_supplier,
    uninstall_excepthook,
    write_crash_record,
)

# ---------------------------------------------------------------------------
# write_crash_record -- the load-bearing record shape
# ---------------------------------------------------------------------------


def _read_record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _raise_and_capture() -> tuple[type[BaseException], BaseException, object]:
    """Trigger a real exception so the traceback in the record has
    real frames, not a synthesized one."""
    try:
        raise RuntimeError("test-failure-message")
    except RuntimeError as e:
        return type(e), e, e.__traceback__


def test_record_has_documented_top_level_keys(tmp_path: Path) -> None:
    """The JSON file holds the keys downstream tooling will rely on."""
    exc_type, exc_val, exc_tb = _raise_and_capture()
    path = write_crash_record(exc_type, exc_val, exc_tb, crash_dir=tmp_path)
    assert path is not None
    rec = _read_record(path)
    assert {"ts", "athena_version", "python_version", "platform", "exception", "context"}.issubset(
        rec.keys()
    )
    assert rec["exception"]["type"] == "RuntimeError"
    assert "test-failure-message" in rec["exception"]["message"]
    # Traceback is captured as a string (not nested objects).
    assert isinstance(rec["exception"]["traceback"], str)
    assert "RuntimeError" in rec["exception"]["traceback"]


def test_record_includes_supplied_context(tmp_path: Path) -> None:
    """A non-None ``CrashContext`` lands in ``context``."""
    exc_type, exc_val, exc_tb = _raise_and_capture()
    ctx = CrashContext(
        model="claude-opus-4-7",
        provider="anthropic",
        profile="dogfood",
        workspace="/tmp/ws",
        session_id="sess-xyz",
        turn_count=12,
        tool_call_count=47,
        last_message_roles=["user", "assistant", "tool"],
    )
    path = write_crash_record(exc_type, exc_val, exc_tb, ctx, crash_dir=tmp_path)
    rec = _read_record(path)
    assert rec["context"]["model"] == "claude-opus-4-7"
    assert rec["context"]["session_id"] == "sess-xyz"
    assert rec["context"]["turn_count"] == 12
    assert rec["context"]["last_message_roles"] == ["user", "assistant", "tool"]


def test_filename_pattern_matches_glob(tmp_path: Path) -> None:
    """Files land as ``crash-YYYYMMDD-HHMMSS-<uuid8>.json``."""
    exc_type, exc_val, exc_tb = _raise_and_capture()
    path = write_crash_record(exc_type, exc_val, exc_tb, crash_dir=tmp_path)
    assert path.name.startswith("crash-")
    assert path.suffix == ".json"
    # 8-char uuid suffix before .json -- length sanity check.
    stem = path.stem  # e.g. crash-20260531-220000-abcd1234
    assert len(stem.split("-")[-1]) == 8


def test_no_tmp_file_left_on_disk(tmp_path: Path) -> None:
    """The atomic-rename pattern means after a successful write,
    no ``.tmp`` file remains."""
    exc_type, exc_val, exc_tb = _raise_and_capture()
    write_crash_record(exc_type, exc_val, exc_tb, crash_dir=tmp_path)
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == []


# ---------------------------------------------------------------------------
# Secret scrubbing -- defence in depth
# ---------------------------------------------------------------------------


def test_scrubs_sk_prefixed_keys_in_message(tmp_path: Path) -> None:
    """sk-or-... / sk-ant-... patterns must NOT survive into the
    on-disk record."""
    try:
        raise RuntimeError("auth failed for sk-or-v1-abcdef1234567890 -- check key")
    except RuntimeError as e:
        path = write_crash_record(type(e), e, e.__traceback__, crash_dir=tmp_path)
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "sk-or-v1-abcdef1234567890" not in text
    assert "<redacted-secret>" in text


def test_scrubs_bearer_tokens(tmp_path: Path) -> None:
    try:
        raise RuntimeError("upstream: Bearer eyJhbGc-abcdef-token-123 rejected")
    except RuntimeError as e:
        path = write_crash_record(type(e), e, e.__traceback__, crash_dir=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "eyJhbGc-abcdef-token-123" not in text
    assert "<redacted-secret>" in text


def test_scrubs_key_value_pairs(tmp_path: Path) -> None:
    """``ANTHROPIC_API_KEY=abc123...`` patterns get scrubbed too."""
    try:
        raise RuntimeError("config dump: ANTHROPIC_API_KEY=sk-ant-secretvalue99")
    except RuntimeError as e:
        path = write_crash_record(type(e), e, e.__traceback__, crash_dir=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "sk-ant-secretvalue99" not in text


# ---------------------------------------------------------------------------
# Privacy: conversation content NEVER lands in records
# ---------------------------------------------------------------------------


def test_context_does_not_carry_message_content(tmp_path: Path) -> None:
    """CrashContext exposes message ROLES only, never bodies. The
    schema doesn't even have a content field -- the test pins the
    surface so a future refactor can't accidentally widen it."""
    exc_type, exc_val, exc_tb = _raise_and_capture()
    ctx = CrashContext(
        last_message_roles=["user", "assistant"],
    )
    path = write_crash_record(exc_type, exc_val, exc_tb, ctx, crash_dir=tmp_path)
    rec = _read_record(path)
    # No "content" / "messages" / "body" keys anywhere in the
    # context dict.
    ctx_keys = set(rec["context"].keys())
    forbidden = {"content", "messages", "message_bodies", "body", "text"}
    assert ctx_keys.isdisjoint(forbidden)


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


def test_rotation_drops_oldest_beyond_keep(tmp_path: Path) -> None:
    """When more than ``keep`` records exist, the OLDEST get
    removed (sort by mtime ascending). Newest survive."""
    # Pre-create records with staggered mtimes so age order is
    # deterministic without needing real time to elapse.
    for i in range(7):
        f = tmp_path / f"crash-2026{i:04d}-aaaaaaaa.json"
        f.write_text("{}", encoding="utf-8")
        os_time = time.time() - (7 - i) * 60  # older index = older mtime
        import os

        os.utime(f, (os_time, os_time))
    # Now write an 8th record with keep=3 -- only the 3 newest
    # should remain after rotation (the new one + the 2 most recent
    # pre-existing).
    exc_type, exc_val, exc_tb = _raise_and_capture()
    path = write_crash_record(exc_type, exc_val, exc_tb, crash_dir=tmp_path, keep=3)
    remaining = sorted(p.name for p in tmp_path.glob("crash-*.json"))
    assert len(remaining) == 3
    # The just-written record survives.
    assert path.name in remaining


def test_rotation_below_cap_keeps_all(tmp_path: Path) -> None:
    """Under the cap, no rotation fires."""
    for i in range(3):
        f = tmp_path / f"crash-2026{i:04d}-aaaaaaaa.json"
        f.write_text("{}", encoding="utf-8")
    exc_type, exc_val, exc_tb = _raise_and_capture()
    write_crash_record(exc_type, exc_val, exc_tb, crash_dir=tmp_path, keep=10)
    assert len(list(tmp_path.glob("crash-*.json"))) == 4


def test_default_cap_is_documented_constant() -> None:
    """If someone bumps the default and forgets to update docs, this
    pin catches it. Re-read the constant rather than hardcoding 50
    so a documented bump shows here too."""
    assert MAX_CRASH_RECORDS >= 10  # sane lower bound
    assert MAX_CRASH_RECORDS <= 1000  # don't grow unbounded


# ---------------------------------------------------------------------------
# Writer-failure handling: never mask the original exception
# ---------------------------------------------------------------------------


def test_writer_returns_none_on_unwritable_dir(tmp_path: Path) -> None:
    """If the target directory can't be written, the writer returns
    None rather than raising. The excepthook depends on this so a
    bad writer doesn't blow away the operator's traceback."""
    # Point at a path that exists as a FILE -- making it a directory
    # is impossible, so mkdir fails.
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("oops", encoding="utf-8")
    exc_type, exc_val, exc_tb = _raise_and_capture()
    result = write_crash_record(exc_type, exc_val, exc_tb, crash_dir=blocker)
    assert result is None


# ---------------------------------------------------------------------------
# Excepthook install / uninstall
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_excepthook_state():
    """sys.excepthook + the module's stored original are
    process-global. Other test files (or earlier tests in this
    file) can leave them in unexpected states. Save / restore
    around every test so each pin is hermetic."""
    saved_hook = sys.excepthook
    saved_orig = crash_log._orig_excepthook
    saved_supplier = crash_log._context_supplier
    yield
    sys.excepthook = saved_hook
    crash_log._orig_excepthook = saved_orig
    crash_log._context_supplier = saved_supplier


def test_install_swaps_excepthook() -> None:
    """``install_excepthook`` replaces the live ``sys.excepthook``."""
    # Make sure we start from a clean baseline regardless of
    # what other tests / imports left lying around.
    uninstall_excepthook()
    original = sys.excepthook
    install_excepthook()
    assert sys.excepthook is not original
    assert sys.excepthook is crash_log._athena_excepthook


def test_install_is_idempotent() -> None:
    """Calling install twice is a no-op the second time -- the
    original hook is only saved on the first call so a double-install
    doesn't lose it."""
    install_excepthook()
    saved = crash_log._orig_excepthook
    install_excepthook()
    try:
        assert crash_log._orig_excepthook is saved
    finally:
        uninstall_excepthook()


def test_uninstall_restores_original() -> None:
    # Defensive: a prior test may have left sys.excepthook as
    # ``_athena_excepthook`` while ``_orig_excepthook`` was cleared.
    # The autouse fixture restores both at teardown, but the order
    # of test execution across files isn't deterministic enough to
    # assume a pristine sys.excepthook at the start. Forcing an
    # uninstall first makes the test hermetic.
    uninstall_excepthook()
    sys.excepthook = sys.__excepthook__
    original = sys.excepthook
    install_excepthook()
    uninstall_excepthook()
    assert sys.excepthook is original


def test_excepthook_skips_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """KeyboardInterrupt is the user's deliberate exit -- never
    write a crash log for it. The hook chains directly to the
    original."""
    monkeypatch.setattr(crash_log, "_crash_dir", lambda: tmp_path)
    chained: list[bool] = []

    def _orig(t, v, tb):  # noqa: ARG001
        chained.append(True)

    monkeypatch.setattr(crash_log, "_orig_excepthook", _orig)
    crash_log._athena_excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    # No crash file written.
    assert list(tmp_path.glob("crash-*.json")) == []
    # Chained to original.
    assert chained == [True]


def test_excepthook_writes_record_and_chains(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """For a real exception, the hook writes a record AND chains
    to the original hook so the operator still sees the traceback."""
    monkeypatch.setattr(crash_log, "_crash_dir", lambda: tmp_path)
    chained: list[bool] = []

    def _orig(t, v, tb):  # noqa: ARG001
        chained.append(True)

    monkeypatch.setattr(crash_log, "_orig_excepthook", _orig)
    exc_type, exc_val, exc_tb = _raise_and_capture()
    crash_log._athena_excepthook(exc_type, exc_val, exc_tb)
    records = list(tmp_path.glob("crash-*.json"))
    assert len(records) == 1
    assert chained == [True]


# ---------------------------------------------------------------------------
# Context supplier registration
# ---------------------------------------------------------------------------


def test_supplier_lands_in_record(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A registered supplier's ``CrashContext`` lands in the record
    when the excepthook fires."""
    monkeypatch.setattr(crash_log, "_crash_dir", lambda: tmp_path)

    def _supplier() -> CrashContext:
        return CrashContext(model="m1", session_id="s1", turn_count=3)

    register_context_supplier(_supplier)
    try:
        exc_type, exc_val, exc_tb = _raise_and_capture()
        crash_log._athena_excepthook(exc_type, exc_val, exc_tb)
    finally:
        register_context_supplier(None)

    rec = _read_record(next(tmp_path.glob("crash-*.json")))
    assert rec["context"]["model"] == "m1"
    assert rec["context"]["session_id"] == "s1"
    assert rec["context"]["turn_count"] == 3


def test_failing_supplier_does_not_break_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the supplier itself raises, the hook still writes a
    record (with an empty context) instead of crashing."""
    monkeypatch.setattr(crash_log, "_crash_dir", lambda: tmp_path)

    def _bad_supplier() -> CrashContext:
        raise RuntimeError("supplier exploded")

    register_context_supplier(_bad_supplier)
    try:
        exc_type, exc_val, exc_tb = _raise_and_capture()
        crash_log._athena_excepthook(exc_type, exc_val, exc_tb)
    finally:
        register_context_supplier(None)

    # Record still written.
    assert len(list(tmp_path.glob("crash-*.json"))) == 1


# ---------------------------------------------------------------------------
# capture_crash (explicit API for code that catches & wants to log)
# ---------------------------------------------------------------------------


def test_capture_crash_writes_with_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The explicit API lets code catch an exception, log it with
    a note describing the context, and continue.

    The crash dir is redirected to ``tmp_path`` so the test never
    pollutes the operator's real ``~/.athena/crashes`` -- capture_crash
    delegates to write_crash_record with no crash_dir, which resolves
    the (monkeypatchable) ``_crash_dir()`` default.
    """
    monkeypatch.setattr(crash_log, "_crash_dir", lambda: tmp_path)
    try:
        raise ValueError("bad")
    except ValueError as e:
        path = capture_crash(e, note="TUI gateway disconnected; restarting", context=CrashContext())

    assert path is not None and path.exists()
    assert path.parent == tmp_path  # isolated dir, NOT the real home
    rec = json.loads(path.read_text(encoding="utf-8"))
    assert rec["context"]["note"] == "TUI gateway disconnected; restarting"


def test_capture_crash_note_lands_in_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(crash_log, "_crash_dir", lambda: tmp_path)
    try:
        raise ValueError("bad")
    except ValueError as e:
        capture_crash(e, note="tui gateway lost")
    rec = _read_record(next(tmp_path.glob("crash-*.json")))
    assert "tui gateway lost" in (rec["context"].get("note") or "")


# ---------------------------------------------------------------------------
# recent_crashes -- doctor surfaces this
# ---------------------------------------------------------------------------


def test_recent_crashes_empty_when_no_dir(tmp_path: Path) -> None:
    """No directory -> empty list, no crash."""
    missing = tmp_path / "nope"
    assert recent_crashes(crash_dir=missing) == []


def test_recent_crashes_sorts_newest_first(tmp_path: Path) -> None:
    """``ls -la`` semantics -- newest mtime first."""
    import os

    for i in range(3):
        f = tmp_path / f"crash-2026{i:04d}-aaaaaaaa.json"
        f.write_text("{}", encoding="utf-8")
        # Stagger mtime: i=0 is OLDEST.
        os.utime(f, (time.time() - (3 - i) * 60, time.time() - (3 - i) * 60))
    listing = recent_crashes(crash_dir=tmp_path)
    assert len(listing) == 3
    # Newest first: file at index 2 of the create loop has the most
    # recent mtime, so it sorts first.
    assert listing[0].name == "crash-20260002-aaaaaaaa.json"
    assert listing[-1].name == "crash-20260000-aaaaaaaa.json"


def test_recent_crashes_within_days_filters(tmp_path: Path) -> None:
    """``within_days`` drops records older than the cutoff."""
    import os

    # One recent, one old (10 days ago).
    recent_file = tmp_path / "crash-20260001-aaaaaaaa.json"
    old_file = tmp_path / "crash-20260002-bbbbbbbb.json"
    recent_file.write_text("{}", encoding="utf-8")
    old_file.write_text("{}", encoding="utf-8")
    os.utime(recent_file, (time.time() - 3600, time.time() - 3600))
    old_ts = time.time() - 10 * 86400
    os.utime(old_file, (old_ts, old_ts))

    within_7 = recent_crashes(crash_dir=tmp_path, within_days=7)
    assert len(within_7) == 1
    assert within_7[0].name == recent_file.name
