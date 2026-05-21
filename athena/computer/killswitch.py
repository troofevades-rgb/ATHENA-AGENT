"""Always-on kill switch for computer use (T6-04.2).

Two engagement paths:

  1. Ctrl+C — a SIGINT handler installed when control becomes
     active. The handler engages the switch synchronously; the
     loop's per-iteration check picks it up at the top of the
     next cycle.

  2. A global hotkey (config ``computer_kill_hotkey``, default
     ``ctrl+alt+k``). Hotkey listening needs an optional
     dependency (``pynput``); when it's absent the hotkey path
     degrades silently and Ctrl+C remains the always-available
     fallback.

The switch is checked at the TOP of every loop iteration. Once
engaged it stays engaged until the loop calls
:func:`disengage` on exit — so a Ctrl+C during a sleep between
actions is honoured on the next iteration; a Ctrl+C during the
`perform` call interrupts via the SIGINT signal directly (the
backend's perform routines should run quickly enough that the
signal lands cleanly).

This module is intentionally importable + testable with NO
real input backend present. The hotkey listener is the only
piece that depends on an optional dep; everything else runs in
unit tests.
"""

from __future__ import annotations

import dataclasses
import logging
import signal
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level engagement state
# ---------------------------------------------------------------------------


_lock = threading.Lock()
_engaged = False
_engaged_reason: str | None = None

# Tracks the prior SIGINT handler so :func:`disengage` can
# restore it. Set when :func:`arm` installs the handler.
_prior_sigint: Any = None
_armed: bool = False
_hotkey_listener: Any = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_engaged() -> bool:
    """Return True iff the kill switch is currently engaged.

    The loop polls this at the top of every iteration. A True
    return means the loop must abort cleanly — no further
    backend.perform calls, no further screenshots.
    """
    return _engaged


def engaged_reason() -> str | None:
    """Human-readable reason the switch engaged (for audit logs
    + UI messages). None when disengaged."""
    return _engaged_reason


def engage(reason: str = "engaged") -> None:
    """Trip the switch. Thread-safe; idempotent. Reason is the
    first one set (subsequent calls don't overwrite — the
    earliest reason is the actionable one for the user)."""
    global _engaged, _engaged_reason
    with _lock:
        if not _engaged:
            _engaged = True
            _engaged_reason = reason
            logger.warning("computer kill switch engaged: %s", reason)


def disengage() -> None:
    """Reset the switch. Called by the loop on a clean exit so
    the next task can start. Also restores the prior SIGINT
    handler if :func:`arm` had installed one."""
    global _engaged, _engaged_reason, _armed, _prior_sigint, _hotkey_listener
    with _lock:
        _engaged = False
        _engaged_reason = None
        if _armed:
            try:
                signal.signal(signal.SIGINT, _prior_sigint or signal.SIG_DFL)
            except (ValueError, TypeError):
                # signal.signal raises ValueError when called
                # from a non-main thread; that's fine — the loop
                # already isn't running.
                pass
            _prior_sigint = None
            _armed = False
        if _hotkey_listener is not None:
            try:
                _hotkey_listener.stop()
            except Exception:  # noqa: BLE001
                pass
            _hotkey_listener = None


def arm(*, hotkey: str | None = None) -> None:
    """Activate the always-on safety net.

    Installs:

      * SIGINT handler that engages the switch on Ctrl+C
      * Hotkey listener for ``hotkey`` (best-effort — silently
        degrades when the optional ``pynput`` dependency isn't
        installed)

    Idempotent: calling :func:`arm` while already armed is a
    no-op. Always call :func:`disengage` to clean up.
    """
    global _armed, _prior_sigint, _hotkey_listener
    with _lock:
        if _armed:
            return
        # Reset the engaged flag on arm so a stale engagement
        # from a prior session doesn't immediately halt this
        # one.
        _reset_engagement_unlocked()
        try:
            _prior_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, _sigint_handler)
        except (ValueError, TypeError) as e:
            # Non-main thread → can't install. We can still
            # arm without Ctrl+C; the hotkey path remains.
            logger.debug("kill switch: could not install SIGINT handler: %s", e)
            _prior_sigint = None
        _armed = True

    # Hotkey listener is best-effort; pynput is optional. Run
    # OUTSIDE the lock so a slow start-up doesn't block other
    # threads.
    if hotkey:
        _hotkey_listener = _try_start_hotkey_listener(hotkey)


def _reset_engagement_unlocked() -> None:
    """Clear engagement state WITHOUT touching the SIGINT
    handler — caller already holds _lock."""
    global _engaged, _engaged_reason
    _engaged = False
    _engaged_reason = None


def reset_for_tests() -> None:
    """Test-only helper: fully reset module state. Production
    code uses :func:`disengage`."""
    global _engaged, _engaged_reason, _armed, _prior_sigint, _hotkey_listener
    with _lock:
        _engaged = False
        _engaged_reason = None
        if _hotkey_listener is not None:
            try:
                _hotkey_listener.stop()
            except Exception:  # noqa: BLE001
                pass
            _hotkey_listener = None
        _armed = False
        _prior_sigint = None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _sigint_handler(signum, frame):  # noqa: ARG001 — signal handler signature
    """SIGINT handler — engages the switch then re-raises so
    downstream code that catches KeyboardInterrupt (the agent's
    existing turn-cancel paths) sees the same signal it always
    has."""
    engage(reason="Ctrl+C")
    raise KeyboardInterrupt()


def _try_start_hotkey_listener(hotkey: str) -> Any:
    """Best-effort hotkey listener. Returns the listener handle
    or None when the optional dependency is unavailable.

    The listener fires :func:`engage` from a background thread
    when the configured key combination is pressed. Athena does
    not bundle a hotkey library by default; the user installs
    one explicitly to enable this path."""
    try:
        from pynput import keyboard  # type: ignore[import-untyped]
    except ImportError:
        logger.info(
            "kill switch: pynput not installed; hotkey %r unavailable, "
            "Ctrl+C remains active",
            hotkey,
        )
        return None

    parsed = _parse_hotkey(hotkey)
    if parsed is None:
        logger.warning("kill switch: could not parse hotkey %r", hotkey)
        return None

    def _on_hotkey() -> None:
        engage(reason=f"hotkey {hotkey}")

    try:
        # keyboard.GlobalHotKeys runs its own listener thread.
        listener = keyboard.GlobalHotKeys({parsed: _on_hotkey})
        listener.start()
    except Exception as e:  # noqa: BLE001
        logger.warning("kill switch: hotkey listener failed: %s", e)
        return None
    return listener


def _parse_hotkey(hotkey: str) -> str | None:
    """Translate "ctrl+alt+k" → "<ctrl>+<alt>+k" (pynput's
    expected format). Returns None when the input doesn't
    parse cleanly."""
    if not hotkey:
        return None
    parts = [p.strip().lower() for p in hotkey.split("+")]
    if not all(parts):
        return None
    out: list[str] = []
    for p in parts:
        if p in ("ctrl", "control"):
            out.append("<ctrl>")
        elif p == "alt":
            out.append("<alt>")
        elif p in ("shift",):
            out.append("<shift>")
        elif p in ("cmd", "meta", "win", "super"):
            out.append("<cmd>")
        elif len(p) == 1:
            out.append(p)
        else:
            # Function keys / named keys — pynput accepts them
            # as <name> form. Best effort: f1, esc, tab, etc.
            out.append(f"<{p}>")
    return "+".join(out)


# ---------------------------------------------------------------------------
# Polling helper for the loop (T6-04.5)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class HaltDecision:
    """One poll result from :func:`poll_for_halt`."""

    halted: bool
    reason: str | None


def poll_for_halt() -> HaltDecision:
    """Convenience accessor for the loop — returns a single
    object the loop can pattern-match on. Equivalent to
    ``HaltDecision(is_engaged(), engaged_reason())`` with the
    pair captured atomically."""
    with _lock:
        return HaltDecision(halted=_engaged, reason=_engaged_reason)
