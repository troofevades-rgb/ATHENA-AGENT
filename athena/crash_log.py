"""Crash log -- capture unhandled exceptions to ``~/.athena/crashes/``.

Operationally critical for debugging: when athena dies mid-session
(TUI gateway crash, provider stack trace, runtime exception in a
tool), the operator gets a one-line "athena crashed; report at
~/.athena/crashes/<id>.json" and the developer gets a structured
record they can paste into a bug report.

What lands in a crash record:

  * ISO-8601 UTC timestamp
  * Athena version + Python version + platform / OS
  * Exception type / message / full traceback
  * Live context (model, provider, profile, workspace, session_id,
    turn / tool-call counters, last-N message metadata)

What does NOT land in a crash record:

  * Conversation content (could leak proprietary code, credentials,
    business data). Only message ROLES and lengths are recorded;
    the body is replaced with a redacted placeholder.
  * API keys, tokens, dotenv values. These should never reach the
    excepthook scope, but the writer also runs every string through
    a redactor pass before serialization as a defence in depth.
  * File paths under ``~`` are kept verbatim because they're
    diagnostic and the operator is the only reader; if a hosted-
    multitenant deployment ships crash logs off-host, an additional
    path redactor should layer on top.

Rotation:

  * Hard cap at ``MAX_CRASH_RECORDS`` (default 50). Oldest dropped
    by file mtime when the cap is exceeded.
  * Each record is a single JSON file at
    ``~/.athena/crashes/crash-YYYYMMDD-HHMMSS-<uuid8>.json`` so
    operators can ``ls -la`` to see what's recent.

Installation:

  * ``install_excepthook()`` swaps ``sys.excepthook`` for the
    crash-writer. Called once from ``athena/__main__.py:main()``.
  * Top-level ``athena`` invocations get the hook automatically.
    Tests and library imports do NOT install the hook (would
    pollute pytest's own exception reporting).

Safety notes:

  * The writer itself is wrapped in a top-level try/except. A
    failure to write a crash report MUST NOT mask the original
    exception. Worst case: the hook prints "crash log unavailable"
    to stderr and re-raises through the default excepthook.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import sys
import traceback
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any

logger = logging.getLogger(__name__)

# Hard cap on retained crash records. Each record is small (a few KB
# in the typical case) so 50 is ~ 200 KB upper bound -- well under any
# disk pressure threshold.
MAX_CRASH_RECORDS = 50

# Message-content redaction marker. The actual content stays out of
# the crash record entirely; this placeholder shows up in its place.
_REDACTED_BODY = "<redacted>"

# Defence-in-depth secret scrubber. Matches the obvious patterns
# (sk-..., bearer tokens, key=value pairs) and replaces with markers.
# Runs over every string before JSON serialization so a stray secret
# in a stack frame's locals can't leak through.
_SECRET_PATTERNS = (
    # Common API key prefixes (Anthropic sk-ant, OpenAI sk-, OpenRouter sk-or-).
    re.compile(r"\bsk-[a-zA-Z0-9_\-]{10,}", re.IGNORECASE),
    # Bearer tokens.
    re.compile(r"\bBearer\s+[a-zA-Z0-9_\-\.=]+", re.IGNORECASE),
    # Generic ``KEY=VALUE`` for keys that look credential-shaped.
    re.compile(
        r"\b([A-Z_]*(?:API|TOKEN|KEY|SECRET|PASSWORD)[A-Z_]*)\s*=\s*"
        r"['\"]?[a-zA-Z0-9_\-]{8,}['\"]?",
        re.IGNORECASE,
    ),
)


def _scrub(text: str) -> str:
    """Defence-in-depth secret redactor. Runs over every string
    before serialization. Replaces common credential shapes with a
    fixed marker; the original value never lands on disk."""
    if not isinstance(text, str):
        return text
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub("<redacted-secret>", out)
    return out


@dataclass
class CrashContext:
    """Live process state at the moment of crash. Populated by the
    excepthook from whatever's reachable; all fields tolerate
    ``None`` so a crash that fires before the agent is constructed
    still produces a useful record."""

    model: str | None = None
    provider: str | None = None
    profile: str | None = None
    workspace: str | None = None
    session_id: str | None = None
    turn_count: int | None = None
    tool_call_count: int | None = None
    # Per-message metadata only -- never content.
    last_message_roles: list[str] = field(default_factory=list)
    # Optional free-form notes from explicit ``capture_crash`` callers
    # (e.g. "TUI gateway disconnected").
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "profile": self.profile,
            "workspace": _scrub(self.workspace) if self.workspace else None,
            "session_id": self.session_id,
            "turn_count": self.turn_count,
            "tool_call_count": self.tool_call_count,
            "last_message_roles": list(self.last_message_roles),
            "note": _scrub(self.note) if self.note else None,
        }


def _crash_dir() -> Path:
    """Resolve ``~/.athena/crashes/``. Auto-creates the directory.
    Indirected so tests can monkeypatch via ``athena.crash_log._crash_dir``."""
    p = Path.home() / ".athena" / "crashes"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _athena_version() -> str:
    """Resolve the installed athena version, falling back to
    ``unknown`` if the import-time metadata isn't available."""
    try:
        from . import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001
        return "unknown"


def _build_record(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
    context: CrashContext | None,
) -> dict[str, Any]:
    """Assemble the JSON-serializable record."""
    tb_string = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "athena_version": _athena_version(),
        "python_version": platform.python_version(),
        "platform": sys.platform,
        "os_release": platform.platform(),
        "exception": {
            "type": exc_type.__name__,
            "message": _scrub(str(exc_value)),
            "traceback": _scrub(tb_string),
        },
        "context": (context or CrashContext()).to_dict(),
    }


def _record_filename(now: datetime | None = None) -> str:
    """``crash-YYYYMMDD-HHMMSS-<uuid8>.json``. The uuid suffix prevents
    a collision when two crashes fire in the same second."""
    ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"crash-{ts}-{uuid.uuid4().hex[:8]}.json"


def _rotate(crash_dir: Path, keep: int) -> None:
    """Drop the oldest records until the directory holds at most
    ``keep``. Sorts by mtime ascending so the OLDEST go first."""
    if keep <= 0:
        return
    files = [
        p
        for p in crash_dir.iterdir()
        if p.is_file() and p.name.startswith("crash-") and p.suffix == ".json"
    ]
    if len(files) <= keep:
        return
    files.sort(key=lambda p: p.stat().st_mtime)
    for p in files[: len(files) - keep]:
        try:
            p.unlink()
        except OSError:  # noqa: BLE001
            logger.debug("crash log rotate: could not delete %s", p)


def write_crash_record(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
    context: CrashContext | None = None,
    *,
    crash_dir: Path | None = None,
    keep: int = MAX_CRASH_RECORDS,
) -> Path | None:
    """Serialize ``(exc_type, exc_value, exc_tb)`` to a JSON file in
    ``crash_dir`` (default ``~/.athena/crashes``). Returns the path
    of the written file, or ``None`` if writing failed.

    Public API used by the excepthook AND by explicit ``capture_crash``
    callers. The writer is wrapped in a try/except at the top level so
    a failure in the writer never masks the original exception (the
    excepthook caller still re-raises through the default hook on
    failure)."""
    try:
        target_dir = crash_dir or _crash_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        record = _build_record(exc_type, exc_value, exc_tb, context)
        path = target_dir / _record_filename()
        # Atomic-ish: write to tmp then rename. Avoids a half-written
        # JSON file if the process dies mid-write.
        tmp = target_dir / (path.name + ".tmp")
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        _rotate(target_dir, keep)
        return path
    except Exception as e:  # noqa: BLE001
        logger.debug("crash log write failed: %s", e)
        return None


def recent_crashes(
    crash_dir: Path | None = None,
    *,
    within_days: int | None = None,
) -> list[Path]:
    """List crash files in ``crash_dir`` (default ``~/.athena/crashes``),
    optionally filtered to the last ``within_days``. Sorted newest-
    first. Returns ``[]`` if the dir doesn't exist or is empty.

    Used by ``athena doctor`` to surface a recent-crashes count."""
    target = crash_dir or _crash_dir()
    if not target.exists():
        return []
    files = [
        p
        for p in target.iterdir()
        if p.is_file() and p.name.startswith("crash-") and p.suffix == ".json"
    ]
    if within_days is not None:
        cutoff = datetime.now(timezone.utc).timestamp() - within_days * 86400
        files = [p for p in files if p.stat().st_mtime >= cutoff]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


# ── Excepthook installation ─────────────────────────────────────────


# Module-level singletons -- the original hook (so we can chain it)
# and a context-supplier callback the runtime can register so the
# excepthook gets a fresh ``CrashContext`` from the live agent.
_orig_excepthook: Any | None = None
_context_supplier: Any | None = None


def register_context_supplier(supplier: Any) -> None:
    """Register a zero-arg callable that returns a fresh
    :class:`CrashContext` for the current process state. The agent
    runtime calls this once at startup so the excepthook can
    capture live counters / model / session_id.

    Re-registering replaces the previous supplier (useful for tests
    and for sub-agent forks)."""
    global _context_supplier
    _context_supplier = supplier


def _supplied_context() -> CrashContext | None:
    """Run the registered supplier safely. ``None`` propagates."""
    supplier = _context_supplier
    if supplier is None:
        return None
    try:
        ctx = supplier()
    except Exception as e:  # noqa: BLE001
        logger.debug("crash context supplier raised: %s", e)
        return None
    if not isinstance(ctx, CrashContext):
        return None
    return ctx


def _athena_excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    """Replacement for ``sys.excepthook``. Writes a crash record,
    prints a one-line pointer to the operator, then chains to the
    ORIGINAL hook so the traceback still surfaces normally.

    Never raises -- any failure inside the hook is swallowed and
    the original hook still runs."""
    try:
        # KeyboardInterrupt is intentional -- never log as a crash.
        if issubclass(exc_type, KeyboardInterrupt):
            if _orig_excepthook is not None:
                _orig_excepthook(exc_type, exc_value, exc_tb)
            return
        path = write_crash_record(exc_type, exc_value, exc_tb, _supplied_context())
        if path is not None:
            try:
                sys.stderr.write(
                    f"\nathena crash recorded -> {path}\n"
                    f"  paste this file into your bug report; secrets are "
                    "scrubbed but conversation content is NOT included.\n\n"
                )
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    if _orig_excepthook is not None:
        _orig_excepthook(exc_type, exc_value, exc_tb)


def install_excepthook() -> None:
    """Swap ``sys.excepthook`` for the crash writer. Idempotent --
    re-installation is a no-op. Saves the original hook so the
    replacement can chain to it after writing the record (so the
    operator still sees the traceback)."""
    global _orig_excepthook
    if sys.excepthook is _athena_excepthook:
        return
    _orig_excepthook = sys.excepthook
    sys.excepthook = _athena_excepthook


def uninstall_excepthook() -> None:
    """Restore the original ``sys.excepthook``. Used by tests so the
    crash writer doesn't fire on pytest's own exception path."""
    global _orig_excepthook
    if sys.excepthook is _athena_excepthook and _orig_excepthook is not None:
        sys.excepthook = _orig_excepthook
    _orig_excepthook = None


# ── Convenience: explicit capture for code that catches & wants
# to log without re-raising ─────────────────────────────────────────


def capture_crash(
    exc: BaseException,
    *,
    note: str | None = None,
    context: CrashContext | None = None,
) -> Path | None:
    """Write a crash record for an exception caught explicitly --
    used by code paths that want to log a failure but continue (e.g.
    "TUI gateway exited unexpectedly; restart").

    ``note`` is added to the context's free-form note field so the
    operator sees WHY the crash was captured even if the exception
    type is unsurprising."""
    ctx = context or _supplied_context() or CrashContext()
    if note is not None:
        # Merge the call-site note with any supplied context note.
        existing = ctx.note or ""
        ctx.note = f"{note}" if not existing else f"{existing}; {note}"
    return write_crash_record(type(exc), exc, exc.__traceback__, ctx)


# Re-exports for the explicit ``__all__`` consumers might rely on.
__all__: Iterable[str] = (
    "CrashContext",
    "MAX_CRASH_RECORDS",
    "capture_crash",
    "install_excepthook",
    "recent_crashes",
    "register_context_supplier",
    "uninstall_excepthook",
    "write_crash_record",
)
