"""Dependency-light text helpers shared across surfaces.

This module deliberately imports nothing beyond the stdlib so it is
safe to use from the server-side gateway (where pulling in ``ui.py``
would drag in Rich and reconfigure stdout) as well as from the
terminal UI.
"""

from __future__ import annotations

import re

_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", flags=re.DOTALL)
_OPEN_THINK = "<think>"


def strip_think_blocks(
    text: str,
    *,
    closed_replacement: str = "",
    open_replacement: str = "",
) -> str:
    """Remove ``<think>...</think>`` chain-of-thought from ``text``.

    Closed blocks are replaced with ``closed_replacement``. A trailing
    *unclosed* ``<think>`` (the model was cut off mid-thought, common on
    interrupt) is truncated at the opener and replaced with
    ``open_replacement``.

    Defaults strip the thinking out entirely (both replacements empty),
    which is what a chat transport wants. The terminal renderer passes
    non-empty markers so the reader can see a thought happened.
    """
    out = _THINK_BLOCK.sub(closed_replacement, text)
    idx = out.find(_OPEN_THINK)
    if idx != -1:
        out = out[:idx] + open_replacement
    return out
