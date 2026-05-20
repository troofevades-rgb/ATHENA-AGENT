"""Suggestion enhancer — optionally refines the classifier baseline (T3-05R.4).

The classifier already attaches ``auto_label`` to every trajectory
in :func:`ReviewSession.pending`. This module builds the
:class:`SuggestionFn` callable the TUI uses to decide what to
recommend, layering an OPTIONAL skill-metrics signal on top:

- If T3-06 skill metrics exist for the trajectory's skill AND the
  skill has a strong historical label distribution (≥ N
  invocations, ≥ THRESHOLD agreement), the metrics signal overrides
  the classifier suggestion.
- Otherwise the classifier signal is returned as-is.
- When metrics aren't installed / aren't readable, the function
  silently falls back to classifier-only. T3-06 is a soft dep.

Skill identification: the trajectory's metadata may carry a
``"skill_name"`` key (set by the agent when a skill explicitly
fires). When missing, this module looks for the first
``tool_call`` whose ``function.name`` starts with ``"skill_"`` /
``"athena_skill"``, then peels the skill name out. Defence-in-depth
heuristic; the metrics override only fires when we can confidently
attribute the trajectory to a skill.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .classifier import Trajectory
from .review_tui import Suggestion

logger = logging.getLogger(__name__)


# Configurable thresholds — exposed so docs/tests can reference them.
MIN_INVOCATIONS_FOR_OVERRIDE = 10
OVERRIDE_THRESHOLD = 0.95


SuggestionFn = Callable[[Trajectory], "Suggestion | None"]


def build_suggestion_fn(profile_dir: Path | None = None) -> SuggestionFn:
    """Return the :class:`SuggestionFn` the TUI should use.

    Looks for ``<profile_dir>/skill_metrics.jsonl`` (the format
    T3-06 will write). If absent, returns a classifier-only
    suggestion function — no error, no warning logged at INFO
    level, just graceful degradation.
    """
    metrics = _load_metrics(profile_dir) if profile_dir is not None else None

    def _suggest(trajectory: Trajectory) -> Suggestion | None:
        classifier_label = trajectory.auto_label
        skill = _extract_skill_name(trajectory)
        if skill is not None and metrics is not None:
            override = _metrics_override(skill, metrics)
            if override is not None:
                return override
        if classifier_label in ("good", "bad", "preference_pair"):
            return Suggestion(label=classifier_label, source="classifier")
        return None

    return _suggest


# ---------------------------------------------------------------------------
# Metrics loading
# ---------------------------------------------------------------------------


def _load_metrics(profile_dir: Path) -> dict[str, dict[str, int]] | None:
    """Return ``{skill_name: {"good": n, "bad": n, "preference_pair": n}}``
    from ``<profile_dir>/skill_metrics.jsonl``, or ``None`` if the
    file is missing or malformed.

    Each line is a flat JSON object with at least ``skill_name`` and
    a label-count map; we aggregate across lines so the file can be
    append-only (which is how T3-06 plans to write it). Unknown
    fields are tolerated and ignored.
    """
    path = profile_dir / "skill_metrics.jsonl"
    if not path.exists():
        return None
    out: dict[str, dict[str, int]] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.debug("skill_metrics read failed: %s", e)
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        name = rec.get("skill_name")
        if not isinstance(name, str) or not name:
            continue
        bucket = out.setdefault(name, {"good": 0, "bad": 0, "preference_pair": 0})
        for k in ("good", "bad", "preference_pair"):
            v = rec.get(k)
            if isinstance(v, int):
                bucket[k] += v
    return out


def _metrics_override(skill_name: str, metrics: dict[str, dict[str, int]]) -> Suggestion | None:
    dist = metrics.get(skill_name)
    if not dist:
        return None
    decisive = dist.get("good", 0) + dist.get("bad", 0)
    if decisive < MIN_INVOCATIONS_FOR_OVERRIDE:
        return None
    good = dist.get("good", 0)
    bad = dist.get("bad", 0)
    good_ratio = good / decisive
    bad_ratio = bad / decisive
    if good_ratio >= OVERRIDE_THRESHOLD:
        return Suggestion(
            label="good",
            source="metrics",
            confidence=good_ratio,
        )
    if bad_ratio >= OVERRIDE_THRESHOLD:
        return Suggestion(
            label="bad",
            source="metrics",
            confidence=bad_ratio,
        )
    return None


# ---------------------------------------------------------------------------
# Skill identification
# ---------------------------------------------------------------------------


def _extract_skill_name(trajectory: Trajectory) -> str | None:
    """Best-effort: extract the skill the trajectory invoked.

    Checks the explicit metadata field first (set by the agent when
    a skill kicked off the turn), then falls back to scanning
    ``tool_calls`` for skill-shaped function names."""
    meta = trajectory.metadata or {}
    if isinstance(meta, dict):
        name = meta.get("skill_name")
        if isinstance(name, str) and name:
            return name
    for msg in trajectory.turns or []:
        for tc in msg.get("tool_calls") or []:
            fn = (tc.get("function") or {}).get("name", "")
            if not isinstance(fn, str):
                continue
            if fn.startswith("skill_"):
                return fn.removeprefix("skill_")
            if fn.startswith("athena_skill_"):
                return fn.removeprefix("athena_skill_")
    return None


# ---------------------------------------------------------------------------
# Direct accessor for tests
# ---------------------------------------------------------------------------


def metrics_override_for(skill_name: str, metrics: dict[str, dict[str, int]]) -> Suggestion | None:
    """Public alias for :func:`_metrics_override` so tests don't
    reach into a private helper."""
    return _metrics_override(skill_name, metrics)


def extract_skill_name_from(trajectory: Trajectory) -> str | None:
    """Public alias for :func:`_extract_skill_name`."""
    return _extract_skill_name(trajectory)


# Re-export ``Any`` is unnecessary; keep this module's API surface
# small. The TUI imports build_suggestion_fn + Suggestion (the
# latter from review_tui).
_ = Any  # silence unused-import linters when the runtime path doesn't use it
