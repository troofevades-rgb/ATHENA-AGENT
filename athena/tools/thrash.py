"""Detect repeat-with-same-result tool-call loops.

A model can get stuck calling the same tool with the same arguments
multiple times in a row when:

  - A tool returns an error message and the model retries verbatim
  - A tool returns identical data the model reads as "I haven't seen
    this yet" each time
  - The model loses track of what it just called across turns

When the same ``(tool_name, arguments)`` tuple appears ``THRESHOLD``
times in a row AND each call returned the same result, the next
identical call short-circuits with a synthetic warning. The warning
surfaces a preview of the prior result so the model still has the
data, and tells it explicitly to change approach.

State is a per-process ring buffer. Call :func:`reset` between
sessions; the buffer also self-bounds via ``maxlen``.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Threshold of 2 means the *third* consecutive identical call gets the
# synthetic warning. Lower would be too aggressive (one accidental
# double-call would trigger); higher wastes more turns before the
# circuit-breaker fires.
THRESHOLD = 2
BUFFER_MAX = 8
PREVIEW_CHARS = 1000


@dataclass(frozen=True)
class _CallRecord:
    tool: str
    args_hash: str
    result_hash: str
    result_preview: str


_HISTORY: deque[_CallRecord] = deque(maxlen=BUFFER_MAX)


# Argument keys that name a filesystem path. Values under these keys
# get normalized (MSYS-fix, expanduser, workspace-relative resolve)
# before hashing, so semantic-duplicate calls like
#   list_dir(path="/c/Users/foo")
#   list_dir(path="C:\\Users\\foo")
#   list_dir(path="~/foo")
# hash to the same key and a third identical call trips the warning.
# Non-path keys (e.g. "description", "query") are hashed raw — paths
# inside prose shouldn't collapse.
_PATH_ARG_KEYS: frozenset[str] = frozenset({
    "path", "file_path", "dir", "directory", "filename", "file",
    "target", "from_path", "to_path", "src", "dst", "source", "dest",
})


def _normalize_path_value(v: str) -> str:
    """Best-effort canonical form for a path-shaped argument.

    Applies the same MSYS fix the file tools use, expands ``~``, and
    resolves against the agent's workspace if the path is relative.
    Returns the resolved POSIX form. Any failure falls back to ``v``
    unchanged — thrash detection must never raise.
    """
    try:
        from ..safety.path_security import normalize_msys_path
        from .file_ops import _WORKSPACE

        s = str(normalize_msys_path(v))
        p = Path(s).expanduser()
        if not p.is_absolute():
            p = _WORKSPACE / p
        return p.resolve().as_posix()
    except Exception:  # noqa: BLE001
        return v


def _canonical_args(args: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``args`` with path-shaped values canonicalized.

    The original dict is left alone so the model still sees its
    verbatim arguments — this is only the form used for hash equality.
    """
    out: dict[str, Any] = {}
    for k, v in args.items():
        if k in _PATH_ARG_KEYS and isinstance(v, str) and v:
            out[k] = _normalize_path_value(v)
        else:
            out[k] = v
    return out


def _hash_args(args: dict[str, Any]) -> str:
    canon_args = _canonical_args(args)
    try:
        canon = json.dumps(canon_args, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        canon = repr(canon_args)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:12]


def _hash_result(result: str) -> str:
    return hashlib.sha1(result.encode("utf-8")).hexdigest()[:12]


def precheck(tool_name: str, args: dict[str, Any]) -> str | None:
    """If the last THRESHOLD calls were ``(tool_name, args, result)``
    all identical, return a synthetic warning string to substitute for
    the next identical call. Otherwise return None and the caller
    should dispatch normally.
    """
    if len(_HISTORY) < THRESHOLD:
        return None
    args_h = _hash_args(args)
    recent = list(_HISTORY)[-THRESHOLD:]
    if not all(r.tool == tool_name and r.args_hash == args_h for r in recent):
        return None
    if len({r.result_hash for r in recent}) != 1:
        return None
    preview = recent[-1].result_preview
    return (
        f"THRASH WARNING: you just called {tool_name!r} with these exact "
        f"arguments {THRESHOLD} times in a row and the result was "
        f"identical every time. A {THRESHOLD + 1}th identical call would "
        f"return the same thing. Change your approach — different "
        f"arguments, a different tool, or take what you already have and "
        f"move on.\n\n"
        f"--- prior result (truncated to {PREVIEW_CHARS} chars) ---\n"
        f"{preview}"
    )


def record(tool_name: str, args: dict[str, Any], result: str) -> None:
    """Append a completed call to the history buffer."""
    preview = result[:PREVIEW_CHARS]
    if len(result) > PREVIEW_CHARS:
        preview += f"\n... (truncated; {len(result)} chars total)"
    _HISTORY.append(
        _CallRecord(
            tool=tool_name,
            args_hash=_hash_args(args),
            result_hash=_hash_result(result),
            result_preview=preview,
        )
    )


def reset() -> None:
    """Clear the buffer. Call between sessions / on /clear."""
    _HISTORY.clear()
