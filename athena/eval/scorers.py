"""Scorer Protocol + built-in implementations (T7-03.1).

A scorer takes the model's answer (``actual: str``) plus the
case's ``expected`` value (any JSON-safe shape) and returns a
:class:`Score` — passed bool + numeric score in [0, 1] +
human-readable details.

Built-in scorers:

  exact      — string equality after strip()
  contains   — expected substring present in actual
  regex      — expected pattern matches actual (re.search)
  json_path  — expected has structure {path: ..., value: ...};
               json.loads(actual)[path] == value

Custom scorers register via :func:`register_scorer` and become
addressable by name from the eval CLI's ``--scorer`` flag and
per-case ``scorer`` field. The registry is module-level so
operator-supplied scorer modules just import + register at
load time — same pattern as athena's provider registry.
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Any, Callable, Protocol


@dataclasses.dataclass(frozen=True)
class Score:
    """One case's scoring outcome.

    ``passed`` is the headline (CI gates branch on it).
    ``score`` is 0..1 for numeric aggregation — binary scorers
    return 1.0 or 0.0; future fuzzy scorers can return partial
    credit.
    ``details`` is a short human-readable string explaining the
    decision (e.g. "actual contains expected", "regex pattern
    did not match", "JSON path 'data.users[0].id' was 12,
    expected 7").
    """

    passed: bool
    score: float
    details: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": bool(self.passed),
            "score": round(float(self.score), 4),
            "details": self.details,
        }


class Scorer(Protocol):
    """The Protocol every scorer satisfies.

    ``context`` carries any per-case metadata the scorer wants
    (e.g. ``case_id``, ``run_id``, the full case dict). Built-
    ins ignore it; custom scorers can use it.
    """

    def __call__(
        self,
        actual: str,
        expected: Any,
        *,
        context: dict[str, Any],
    ) -> Score:
        ...


# ---------------------------------------------------------------
# Registry
# ---------------------------------------------------------------


_REGISTRY: dict[str, Scorer] = {}


def register_scorer(name: str, scorer: Scorer) -> None:
    """Register a scorer under ``name``. Subsequent calls to
    :func:`get_scorer` resolve it; an eval case's ``scorer``
    field and the CLI's ``--scorer NAME`` flag both look it up
    by this name."""
    if not name:
        raise ValueError("scorer name must be non-empty")
    _REGISTRY[name] = scorer


def get_scorer(name: str) -> Scorer:
    """Resolve a registered scorer by name. Raises ``KeyError``
    with a helpful message naming the available scorers when
    not found — typos in ``--scorer NAME`` should fail fast,
    not silently no-op."""
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown scorer {name!r}; available: "
            + ", ".join(sorted(_REGISTRY))
        )
    return _REGISTRY[name]


def list_scorers() -> list[str]:
    """Sorted names of every registered scorer. The eval CLI
    surfaces this in its ``--help`` blurb so operators see
    what's available without grepping the source."""
    return sorted(_REGISTRY)


# ---------------------------------------------------------------
# Built-in scorers
# ---------------------------------------------------------------


def _exact(actual: str, expected: Any, *, context: dict[str, Any]) -> Score:
    """String equality after strip(). The strictest scorer —
    "the output exactly matches what we wrote in the case file"."""
    a = (actual or "").strip()
    e = str(expected if expected is not None else "").strip()
    if a == e:
        return Score(passed=True, score=1.0, details="exact match")
    return Score(
        passed=False, score=0.0,
        details=(
            f"actual {_quote(a, 80)} does not equal expected "
            f"{_quote(e, 80)}"
        ),
    )


def _contains(actual: str, expected: Any, *, context: dict[str, Any]) -> Score:
    """Expected substring present in actual. The lightest
    sanity check — "did the answer mention the right thing"."""
    a = actual or ""
    e = str(expected if expected is not None else "")
    if not e:
        return Score(
            passed=False, score=0.0,
            details="expected is empty (nothing to check for)",
        )
    if e in a:
        return Score(
            passed=True, score=1.0,
            details=f"actual contains expected {_quote(e, 80)}",
        )
    return Score(
        passed=False, score=0.0,
        details=f"actual does not contain expected {_quote(e, 80)}",
    )


def _regex(actual: str, expected: Any, *, context: dict[str, Any]) -> Score:
    """Expected pattern matches actual via ``re.search``. The
    pattern is the expected string; flags can be embedded
    via ``(?i)`` etc."""
    a = actual or ""
    pattern = str(expected if expected is not None else "")
    if not pattern:
        return Score(
            passed=False, score=0.0,
            details="expected pattern is empty",
        )
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return Score(
            passed=False, score=0.0,
            details=f"invalid regex pattern: {e}",
        )
    match = compiled.search(a)
    if match:
        return Score(
            passed=True, score=1.0,
            details=(
                f"regex matched at offset {match.start()}-{match.end()}: "
                f"{_quote(match.group(0), 60)}"
            ),
        )
    return Score(
        passed=False, score=0.0,
        details=f"regex pattern {_quote(pattern, 80)} did not match",
    )


def _json_path(actual: str, expected: Any, *, context: dict[str, Any]) -> Score:
    """The actual is parsed as JSON; ``expected`` is
    ``{"path": "<dotted>", "value": <expected_value>}``.
    Compares ``json.loads(actual)[path]`` to ``value`` for
    equality. Supports dotted paths with numeric indices:
    ``"data.users[0].id"``.

    Fails cleanly when actual isn't JSON or the path doesn't
    resolve — details says which.
    """
    if not isinstance(expected, dict) or "path" not in expected:
        return Score(
            passed=False, score=0.0,
            details=(
                "json_path scorer requires expected = "
                '{"path": "<dotted>", "value": <expected>}'
            ),
        )
    path = str(expected["path"])
    want = expected.get("value")

    try:
        parsed = json.loads(actual or "")
    except json.JSONDecodeError as e:
        return Score(
            passed=False, score=0.0,
            details=f"actual is not valid JSON: {e}",
        )

    try:
        got = _resolve_path(parsed, path)
    except (KeyError, IndexError, TypeError) as e:
        return Score(
            passed=False, score=0.0,
            details=(
                f"path {path!r} did not resolve in actual JSON: "
                f"{type(e).__name__}: {e}"
            ),
        )
    except ValueError as e:
        # _resolve_path raises ValueError for malformed paths
        # (unbalanced brackets). Report as a scorer config error
        # rather than letting the runner's outer except mis-tag it.
        return Score(
            passed=False, score=0.0,
            details=f"json_path scorer: {e}",
        )

    if got == want:
        return Score(
            passed=True, score=1.0,
            details=f"path {path!r} resolved to expected value",
        )
    return Score(
        passed=False, score=0.0,
        details=(
            f"path {path!r} resolved to {_quote(repr(got), 60)}, "
            f"expected {_quote(repr(want), 60)}"
        ),
    )


def _resolve_path(obj: Any, path: str) -> Any:
    """Walk a dotted path with optional ``[N]`` indices.
    ``data.users[0].id`` → ``obj["data"]["users"][0]["id"]``.

    Raises KeyError / IndexError / TypeError on bad navigation
    so the scorer can report which step failed.
    """
    if not path:
        return obj
    # Tokenise: replace [N] with .N for a uniform split, then
    # decide per-token whether the parent should be indexed
    # as int or keyed as str.
    tokens: list[str] = []
    buf = ""
    i = 0
    while i < len(path):
        ch = path[i]
        if ch == ".":
            if buf:
                tokens.append(buf); buf = ""
        elif ch == "[":
            if buf:
                tokens.append(buf); buf = ""
            try:
                j = path.index("]", i)
            except ValueError as e:
                # Unbalanced bracket -- e.g. ``data[0`` -- previously
                # bubbled as a ValueError that the eval runner
                # mis-reported as "scorer raised". Surface a clear
                # error tied to the path string instead.
                raise ValueError(
                    f"json_path scorer: unbalanced '[' in {path!r}"
                ) from e
            tokens.append(path[i + 1: j])
            i = j  # skip past ]
        else:
            buf += ch
        i += 1
    if buf:
        tokens.append(buf)

    cur = obj
    for tok in tokens:
        if isinstance(cur, list):
            try:
                idx = int(tok)
            except ValueError:
                raise TypeError(
                    f"expected integer index at {tok!r}, list at this depth"
                )
            cur = cur[idx]
        elif isinstance(cur, dict):
            if tok in cur:
                cur = cur[tok]
            else:
                # Also accept numeric strings as integers for
                # dicts with numeric keys (rare but possible).
                try:
                    cur = cur[int(tok)]
                except (KeyError, ValueError):
                    raise KeyError(tok)
        else:
            raise TypeError(
                f"can't navigate into {type(cur).__name__} at {tok!r}"
            )
    return cur


def _quote(s: str, limit: int) -> str:
    """Helper for details strings — quote + truncate to keep
    them inspector-friendly."""
    s = s.replace("\n", " ").replace("\r", " ")
    if len(s) > limit:
        return f'"{s[:limit - 1]}…"'
    return f'"{s}"'


# Register built-ins at module import.
register_scorer("exact", _exact)
register_scorer("contains", _contains)
register_scorer("regex", _regex)
register_scorer("json_path", _json_path)
