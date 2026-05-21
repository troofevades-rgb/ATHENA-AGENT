"""Opt-in social-routing heuristic (T6-02.4).

The explicit ``search_x`` tool is the safe path: the model
explicitly asks for social data and the broker routes
deterministically. This module adds an *optional* auto-router
that scans user messages for "search X / what's on X about ..."
phrasing and, when ``cfg.social_router_heuristic`` is True,
injects a ``search_x`` call before the primary model sees the
turn.

**Off by default.** Heuristics misfire; the explicit tool is
unambiguous. The user opts in.

The phrase detector is pure (no I/O), regex-based, and
conservative — only the obvious social-search shapes trip it.
False positives are worse than false negatives here: routing to
the social adapter unnecessarily costs a token and might leak
the user's query to a third-party API they didn't expect; missing
a borderline phrase just means the user adds "search X for"
explicitly.

Surface:

  should_route(text, *, cfg) -> bool
      Cheap gate the agent calls before dispatching a user turn.
      Returns False unless cfg.social_router_heuristic is True
      AND the text looks like a social-search ask.

  extract_query(text) -> str | None
      Pull the query phrase out of the matched text. Returns
      None when no extraction pattern fits — the caller can
      fall back to the full text.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# Conservative phrase patterns. Each pattern captures the query
# portion in group 1. Anchored at the start so a quoted phrase
# mid-sentence (the user describing a past conversation) doesn't
# misfire.
#
# Patterns trigger on:
#   "search X for <q>"
#   "search Twitter for <q>"
#   "search social for <q>"
#   "what's on X about <q>"
#   "what's twitter saying about <q>"
#   "any tweets about <q>"
#   "latest posts on X about <q>"
#   "find tweets about <q>"
#   "look up X for <q>"
#
# Anchors: ^... at start (optional whitespace), word boundaries
# around the social-network token (X | Twitter | social | tweet).
# Case-insensitive.

_SOCIAL_TOKEN = r"(?:X|Twitter|tweets?|social|posts?)"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "search X for <q>"
    re.compile(
        rf"^\s*(?:please\s+)?search\s+{_SOCIAL_TOKEN}\s+(?:for|about)\s+(.+)",
        re.IGNORECASE,
    ),
    # "look up X for <q>"
    re.compile(
        rf"^\s*look\s+up\s+{_SOCIAL_TOKEN}\s+(?:for|about)\s+(.+)",
        re.IGNORECASE,
    ),
    # "what's on X about <q>" / "what is X saying about <q>"
    re.compile(
        rf"^\s*what(?:'s|\s+is|\s+are)?\s+(?:on|happening\s+on)\s+"
        rf"{_SOCIAL_TOKEN}\s+(?:about|on)\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^\s*what(?:'s|\s+is|\s+are)?\s+{_SOCIAL_TOKEN}\s+saying\s+about\s+(.+)",
        re.IGNORECASE,
    ),
    # "any tweets about <q>" / "any posts on X about <q>"
    re.compile(
        rf"^\s*(?:are\s+there\s+any|any)\s+{_SOCIAL_TOKEN}\s+(?:about|on)\s+(.+)",
        re.IGNORECASE,
    ),
    # "latest tweets about <q>" / "latest posts on X about <q>"
    re.compile(
        rf"^\s*(?:latest|recent)\s+(?:posts?\s+(?:on|from)\s+)?{_SOCIAL_TOKEN}"
        rf"\s+(?:about|on)\s+(.+)",
        re.IGNORECASE,
    ),
    # "latest on X about <q>" / "recent on Twitter about <q>"
    re.compile(
        rf"^\s*(?:latest|recent)\s+on\s+{_SOCIAL_TOKEN}\s+(?:about|on)\s+(.+)",
        re.IGNORECASE,
    ),
    # "find tweets about <q>"
    re.compile(
        rf"^\s*find\s+{_SOCIAL_TOKEN}\s+(?:about|on)\s+(.+)",
        re.IGNORECASE,
    ),
)


def should_route(text: str, *, cfg: Any) -> bool:
    """``True`` when ``text`` looks like a social-search request
    AND the heuristic is enabled.

    The two-condition gate is intentional: even when the regex
    fires, the heuristic only routes when the user opted in via
    ``cfg.social_router_heuristic``. The explicit ``search_x``
    tool path remains the default behaviour.
    """
    if not text or not isinstance(text, str):
        return False
    if not getattr(cfg, "social_router_heuristic", False):
        return False
    return _matches(text) is not None


def extract_query(text: str) -> str | None:
    """Pull the captured query phrase out of ``text``. Strips
    surrounding whitespace and a single trailing ``?``. Returns
    None when no pattern matches."""
    if not text or not isinstance(text, str):
        return None
    m = _matches(text)
    if m is None:
        return None
    query = m.group(1).strip()
    if query.endswith("?"):
        query = query[:-1].rstrip()
    return query or None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _matches(text: str) -> re.Match[str] | None:
    for pattern in _PATTERNS:
        m = pattern.match(text)
        if m is not None:
            return m
    return None
