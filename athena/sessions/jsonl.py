"""Append-only JSONL primitives for the session store.

JSONL is the canonical on-disk format: one JSON object per line, trailing
newline. ``read_jsonl`` is tolerant of malformed lines (logs and skips)
because a power-loss in the middle of an ``append_jsonl`` can leave a
partial line at the tail of the file, and we want recovery to be silent.

The optional ``ATHENA_SESSIONS_FSYNC=1`` env flag flushes after each write
— off by default because the hot path (every model turn) is latency-
sensitive and the loss window on crash is at most one turn. The legacy
``OCODE_SESSIONS_FSYNC`` is honored for one release.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterator


logger = logging.getLogger(__name__)


def _fsync_enabled() -> bool:
    raw = (
        os.environ.get("ATHENA_SESSIONS_FSYNC")
        or os.environ.get("OCODE_SESSIONS_FSYNC")
        or ""
    )
    return raw.strip() in ("1", "true", "yes")


def append_jsonl(path: Path, message: dict[str, Any]) -> None:
    """Append one JSON object to ``path`` with a trailing newline.

    The file is created if missing. ``ATHENA_SESSIONS_FSYNC=1`` flushes and
    fsyncs after each write — turn that on if you're running athena on
    flaky storage and care about losing at most one turn.
    """
    line = json.dumps(message, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(line + "\n")
        if _fsync_enabled():
            fh.flush()
            os.fsync(fh.fileno())


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield each parsed JSON object. Malformed lines log a warning and skip."""
    try:
        fh = open(path, "r", encoding="utf-8")
    except FileNotFoundError:
        return
    with fh:
        for lineno, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                yield json.loads(stripped)
            except json.JSONDecodeError as e:
                logger.warning(
                    "skipping malformed JSONL line: %s:%d (%s)",
                    path, lineno, e,
                )


def count_lines(path: Path) -> int:
    """Cheap line counter — used by ``SessionStore.append_turn`` to assign
    the next ``turn_index`` without reading every message back into memory."""
    if not path.exists():
        return 0
    n = 0
    with open(path, "rb") as fh:
        for _ in fh:
            n += 1
    return n
