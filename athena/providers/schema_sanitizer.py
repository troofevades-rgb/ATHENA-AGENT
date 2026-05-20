"""Recover malformed JSON in tool-call arguments.

Local models (Qwen, Llama, Mistral, DeepSeek) emit invalid JSON in
the ``arguments`` field of tool calls at rates of 5–15%. This
module attempts a sequence of forgiving passes to recover the
intended JSON object without speculating about semantics.

Contract:

- Pure function. No I/O, no exceptions raised.
- Operates ONLY on the arguments string. Never modifies the tool
  name (which is taken as a parameter only for logging).
- Refuses to alter semantics — missing values, extra values, or
  ambiguous nesting return None rather than a guessed structure.
- Idempotent — already-valid JSON passes through unchanged with no
  recorded fixes.
- Gated by ``cfg.tool_call_sanitize``; tool dispatch falls back to
  raw json.loads when disabled.

Pass order (first successful parse wins):

  1. Direct json.loads.
  2. Smart quotes (curly, prime, etc.) -> ASCII quotes.
  3. Single-quoted strings -> double-quoted (only if no
     double-quoted strings exist already, to avoid breaking strings
     that contain apostrophes).
  4. Trailing commas (",}" and ",]") removed.
  5. Unquoted top-level keys (``{key:`` or ``,key:``) -> quoted.
  6. Optional demjson3 lenient parser, only if installed locally.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


SMART_QUOTES_TRANSLATION = str.maketrans(
    {
        "‘": "'",  # left single quote
        "’": "'",  # right single quote
        "“": '"',  # left double quote
        "”": '"',  # right double quote
        "′": "'",  # prime
        "″": '"',  # double prime
    }
)


def sanitize_tool_call_args(
    raw: str,
    *,
    tool_name: str = "<unknown>",
) -> tuple[str | None, list[str]]:
    """Try to recover valid JSON from a malformed tool-call args string.

    Returns ``(sanitized_json_string, fixes_applied)`` on success,
    or ``(None, fixes_attempted)`` if no pass produced parseable JSON.

    The caller should pass ``json.loads(sanitized)`` as the tool's
    kwargs. If the first element is ``None``, the caller MUST NOT
    speculate — surface the original parse failure instead.
    """
    fixes: list[str] = []
    if not raw or not raw.strip():
        return None, ["empty input"]

    candidate = raw.strip().lstrip("﻿")

    # Pass 0: direct parse.
    if _try_parse(candidate):
        return candidate, []

    # Pass 1: smart-quote normalisation.
    normalized = candidate.translate(SMART_QUOTES_TRANSLATION)
    if normalized != candidate:
        fixes.append("smart quotes -> ASCII quotes")
        candidate = normalized
        if _try_parse(candidate):
            return candidate, fixes

    # Pass 2: single-quoted strings -> double-quoted (only when
    # there's no double-quoted string already; otherwise we might
    # break "Mike's file"-style apostrophes).
    if "'" in candidate and '"' not in _strip_quoted_substrings(candidate):
        converted = _single_to_double_quotes(candidate)
        if converted != candidate:
            fixes.append("single quotes -> double quotes")
            candidate = converted
            if _try_parse(candidate):
                return candidate, fixes

    # Pass 3: trailing commas inside objects and arrays.
    no_trailing = _remove_trailing_commas(candidate)
    if no_trailing != candidate:
        fixes.append("trailing commas removed")
        candidate = no_trailing
        if _try_parse(candidate):
            return candidate, fixes

    # Pass 4: quote unquoted top-level keys.
    quoted_keys = _quote_unquoted_keys(candidate)
    if quoted_keys != candidate:
        fixes.append("unquoted keys quoted")
        candidate = quoted_keys
        if _try_parse(candidate):
            return candidate, fixes

    # Pass 5: optional demjson3 fallback. Not a hard dependency —
    # only used if the user has demjson3 installed in their env.
    try:
        import demjson3  # type: ignore

        try:
            decoded = demjson3.decode(candidate)
            re_encoded = json.dumps(decoded)
            fixes.append("demjson3 lenient parser")
            return re_encoded, fixes
        except Exception:
            pass
    except ImportError:
        pass

    logger.warning(
        "Could not sanitize tool-call args for tool=%s; "
        "raw payload (truncated): %r; attempted fixes: %s",
        tool_name,
        raw[:500],
        fixes,
    )
    return None, fixes


# ---------------------------------------------------------------------------
# Helper passes
# ---------------------------------------------------------------------------


def _try_parse(s: str) -> bool:
    """Return True if ``s`` parses as JSON."""
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


_DOUBLE_QUOTED_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _strip_quoted_substrings(s: str) -> str:
    """Remove anything inside double-quoted strings.

    Used to safely check whether a string contains double quotes
    OUTSIDE quoted content. Quick-and-dirty; doesn't handle every
    escape sequence perfectly but good enough to gate the
    single-to-double conversion.
    """
    return _DOUBLE_QUOTED_RE.sub("", s)


_SINGLE_QUOTED_RE = re.compile(r"'((?:[^'\\]|\\.)*)'")


def _single_to_double_quotes(s: str) -> str:
    """Convert ``'foo'`` -> ``"foo"`` for each single-quoted token."""
    return _SINGLE_QUOTED_RE.sub(r'"\1"', s)


def _remove_trailing_commas(s: str) -> str:
    """Strip ``,}`` and ``,]`` patterns."""
    s = re.sub(r",\s*\}", "}", s)
    s = re.sub(r",\s*\]", "]", s)
    return s


_UNQUOTED_KEY_RE = re.compile(r"(?P<lead>[\{\,]\s*)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<sep>\s*:)")


def _quote_unquoted_keys(s: str) -> str:
    """Add double quotes around bare identifier keys at object boundaries.

    Matches ``{ key:`` or ``, key:`` (with optional whitespace). Replaces
    with ``{ "key":`` / ``, "key":``. Nested unquoted keys mid-value are
    intentionally NOT touched — too ambiguous to rewrite safely.
    """
    return _UNQUOTED_KEY_RE.sub(r'\g<lead>"\g<key>"\g<sep>', s)
