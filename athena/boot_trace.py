"""Opt-in boot tracer for pinning down silent-exit / hang bugs at startup.

Gated on the env var ``ATHENA_BOOT_TRACE=1``. When OFF (default),
:func:`cp` is a hard no-op with zero filesystem touches — safe to
sprinkle through hot startup paths.

When ON:

  * Each :func:`cp` appends one JSON line to ``~/.athena/boot-trace.jsonl``
    with ``ts``, ``pid``, ``thread`` (name), ``label``, and any
    extra ``data`` kwargs.
  * On the FIRST :func:`cp` of a process, faulthandler is enabled
    against stderr AND ``dump_traceback_later(seconds=30, repeat=True)``
    is armed so any hang dumps every thread's traceback every 30s.
    Crashes (segfault, abort) also write a Python traceback.
  * An ``atexit`` hook writes a final ``"atexit"`` event with the
    exit reason. A silent exit thus produces a final line we can
    correlate against the last reached checkpoint.

Why a separate file rather than reusing event_log: this fires
BEFORE the agent's session_id exists (and event_log is
session-keyed). Boot tracing has to live at module scope.

Why JSONL: lets the operator paste the file straight into a bug
report; tools like ``jq`` parse it without prep.

Privacy: labels and data are written verbatim. Instrumentation
sites must NOT pass secret material into ``cp(...)`` kwargs.
Paths and exception type names are fine; bearer tokens are not.
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

_ENABLED: bool | None = None
_INITIALIZED = False
_LOCK = threading.Lock()
_PATH: Path | None = None


def _enabled() -> bool:
    """Read the env var once and cache. The user toggles via env
    before launch, so re-reading every call is wasted work."""
    global _ENABLED
    if _ENABLED is None:
        _ENABLED = os.environ.get("ATHENA_BOOT_TRACE") == "1"
    return _ENABLED


def _path() -> Path:
    """Resolve and cache the trace file path."""
    global _PATH
    if _PATH is None:
        _PATH = Path.home() / ".athena" / "boot-trace.jsonl"
        _PATH.parent.mkdir(parents=True, exist_ok=True)
    return _PATH


def _initialize_once() -> None:
    """Arm faulthandler + atexit hook the first time tracing fires.
    Idempotent (the lock + flag guarantee single-shot init even
    under thread race)."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _LOCK:
        if _INITIALIZED:
            return
        _INITIALIZED = True
        try:
            import faulthandler

            # CRITICAL: write faulthandler dumps to a FILE, not
            # stderr. The earlier implementation dumped to
            # sys.stderr and raced with Rich Live's spinner
            # rendering (the agent uses ``ui.console.status``
            # while waiting for the provider). On Windows
            # ConPTY, the interleaved writes corrupt the
            # console stream and trigger an "access violation"
            # that crashes the process -- the exact mode the
            # operator saw when this fix was written. A file
            # sink is isolated from terminal rendering and
            # preserves the diagnostic value (the operator
            # opens the log after the hang).
            log_path = Path.home() / ".athena" / "faulthandler.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            # Append mode + line-buffered so previous traces
            # survive across launches; line-buffer flushes
            # each stack frame immediately so a hard crash
            # mid-dump leaves a usable partial.
            fh = open(log_path, "a", buffering=1, encoding="utf-8")
            fh.write(f"\n--- faulthandler armed at {time.time()} pid={os.getpid()} ---\n")
            faulthandler.enable(file=fh, all_threads=True)
            # 60s threshold gives Ollama cold-start (model load
            # + GPU warmup on partial-offload) a chance before
            # we cry "hang". repeat=True still fires every 60s
            # for genuine hangs so the file accumulates evidence.
            faulthandler.dump_traceback_later(60, repeat=True, file=fh)
        except Exception:  # noqa: BLE001
            # faulthandler isn't strictly required for tracing to
            # be useful -- the JSONL still records reached
            # checkpoints. Don't block startup if it can't arm.
            pass
        atexit.register(_atexit_marker)


def _atexit_marker() -> None:
    """Final breadcrumb. If this line is present, exit was clean
    (Python ran atexit hooks). If it's absent, exit was forced
    (``os._exit``, signal, OS abort)."""
    try:
        cp("atexit", exc_info=repr(sys.exc_info()[1]) if sys.exc_info()[1] else None)
    except Exception:  # noqa: BLE001
        # atexit is the last line of defense; never propagate.
        pass


def cp(label: str, **data: Any) -> None:
    """Record one boot-trace checkpoint. No-op when the env var
    isn't set, so callers can sprinkle ``cp("foo")`` freely in
    hot startup paths.

    ``label`` is a short string identifying the site (e.g.
    ``"main_entry"``, ``"agent_init_done"``, ``"mcp_load_pre"``).

    ``data`` lands in the JSONL object verbatim. Keep values
    JSON-serializable; the writer drops the record if not."""
    if not _enabled():
        return
    _initialize_once()
    record: dict[str, Any] = {
        "ts": time.time(),
        "pid": os.getpid(),
        "thread": threading.current_thread().name,
        "label": label,
    }
    if data:
        record["data"] = data
    try:
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    except Exception:  # noqa: BLE001
        # Unlikely (default=str catches most), but tracing must
        # never break the run.
        return
    try:
        with _LOCK:
            with open(_path(), "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    # fsync isn't available on every Windows
                    # filesystem; the flush above is enough for
                    # debugging.
                    pass
    except OSError:
        # Disk full / permission denied — never break the run.
        return


__all__ = ("cp",)
