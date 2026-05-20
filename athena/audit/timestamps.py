"""Parse timestamps with athena's extensions (T3-04).

Accepts:

- ISO 8601 with or without ``Z`` suffix (``2026-05-20T12:00:00Z``,
  ``2026-05-20T12:00:00+00:00``, ``2026-05-20``).
- Relative ago-forms: ``5m``, ``2h``, ``3d``, ``1w``.
- Special tokens:
  - ``now`` — current UTC time
  - ``boot`` / ``session-start`` — first message timestamp from
    the active session JSONL (requires the caller to pass the
    session log path)
  - ``last-checkpoint`` — most recent T3-03 checkpoint's
    ``created_at`` (walks the active profile's checkpoint dirs)
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

_REL_RE = re.compile(r"^(\d+)([smhdw])$")
_DURATIONS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}


class TimestampParseError(ValueError):
    """Raised when a timestamp string can't be resolved."""


def parse_timestamp(
    s: str,
    *,
    session_log_path: Path | None = None,
    profile_dir: Path | None = None,
    now: _dt.datetime | None = None,
) -> _dt.datetime:
    """Resolve ``s`` to a UTC-naive :class:`datetime`.

    ``now`` is injectable for deterministic tests.
    ``session_log_path`` is required for ``boot`` / ``session-start``.
    ``profile_dir`` is required for ``last-checkpoint``.
    """
    if not isinstance(s, str) or not s.strip():
        raise TimestampParseError("empty timestamp")
    s = s.strip()
    current = now if now is not None else _utcnow()

    if s == "now":
        return current

    if s in ("boot", "session-start"):
        return _resolve_session_start(session_log_path)

    if s == "last-checkpoint":
        return _resolve_last_checkpoint(profile_dir)

    m = _REL_RE.match(s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        seconds = n * _DURATIONS[unit]
        return current - _dt.timedelta(seconds=seconds)

    return _parse_iso(s)


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _parse_iso(s: str) -> _dt.datetime:
    """Parse ISO 8601 tolerating the ``Z`` suffix; return UTC-naive."""
    raw = s
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(s)
    except ValueError as e:
        raise TimestampParseError(f"cannot parse timestamp {raw!r}: {e}") from e
    if dt.tzinfo is not None:
        dt = dt.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    return dt


def _resolve_session_start(session_log_path: Path | None) -> _dt.datetime:
    if session_log_path is None or not session_log_path.exists():
        raise TimestampParseError(
            "cannot resolve 'boot' / 'session-start': no active session log path was provided"
        )
    try:
        text = session_log_path.read_text(encoding="utf-8")
    except OSError as e:
        raise TimestampParseError(f"cannot read session log: {e}") from e
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = msg.get("ts") or msg.get("timestamp")
        if ts:
            return _parse_iso(str(ts))
    raise TimestampParseError(
        "no parseable timestamp found in session log; session may have no messages yet"
    )


def _resolve_last_checkpoint(profile_dir: Path | None) -> _dt.datetime:
    if profile_dir is None or not profile_dir.exists():
        raise TimestampParseError(
            "cannot resolve 'last-checkpoint': no profile directory was provided"
        )
    ckpt_root = profile_dir / "checkpoints"
    if not ckpt_root.exists():
        raise TimestampParseError(
            f"cannot resolve 'last-checkpoint': no checkpoints under {ckpt_root}"
        )
    latest_ts: _dt.datetime | None = None
    for ckpt_file in ckpt_root.rglob("cp-*.json"):
        try:
            data = json.loads(ckpt_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        ts_str = data.get("created_at")
        if not ts_str:
            continue
        try:
            ts = _parse_iso(str(ts_str))
        except TimestampParseError:
            continue
        if latest_ts is None or ts > latest_ts:
            latest_ts = ts
    if latest_ts is None:
        raise TimestampParseError(
            "no checkpoints found under the active profile; create one "
            "with `athena checkpoint --label …` first"
        )
    return latest_ts
