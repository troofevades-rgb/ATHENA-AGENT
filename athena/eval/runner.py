"""Eval runner (T7-03.2).

Composes T7-02 batch_run with a scoring pass over each per-
run envelope. Per-case `scorer` field overrides the default;
each case's `expected` is what the scorer compares to the
model's `assistant_text`.

Resume-safety inherits from the batch — if `<output_dir>/<run_id>.json`
already exists, the batch reads it back without re-running. The
scoring pass always runs (cheap; re-scoring lets you iterate
on scorers without re-running the model).

``--baseline DIR`` loads a prior eval's `eval-summary.json` and
computes regressions (cases that PASSED in baseline but FAILED
now) + improvements (cases that FAILED in baseline but PASS
now). Joined by `case_id`; cases without a stable case_id
can't be matched across runs so we mint one for each case at
parse time.
"""

from __future__ import annotations

import datetime
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..batch.manifest import BatchEntry, BatchManifest
from ..batch.runner import _safe_filename, batch_run
from ..config import Config
from .scorers import Score, Scorer, get_scorer
from .summary import (
    EvalCase,
    EvalScore,
    EvalSummary,
    excerpt,
    mint_case_id,
    mint_eval_id,
)

logger = logging.getLogger(__name__)


# ProgressFn — fires once per scored case during the scoring
# pass. The CLI passes a stderr writer.
ProgressFn = Callable[[EvalScore, int, int], None]


def parse_cases_file(path: Path | str) -> list[EvalCase]:
    """Read an eval cases JSONL. One object per line. Blank +
    `#` lines ignored. Raises ``ValueError`` with line numbers
    on malformed input."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"eval cases file not found: {p}")
    cases: list[EvalCase] = []
    for line_no, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError as e:
            raise ValueError(f"cases file line {line_no}: not valid JSON: {e}") from None
        if not isinstance(obj, dict):
            raise ValueError(
                f"cases file line {line_no}: expected an object, got {type(obj).__name__}"
            )
        try:
            cases.append(EvalCase.from_dict(obj))
        except ValueError as e:
            raise ValueError(f"cases file line {line_no}: {e}") from None
    return cases


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _case_to_batch_entry(case: EvalCase) -> BatchEntry:
    """Build the batch entry from the eval case. The case's
    case_id becomes the batch's run_id so eval ↔ batch ↔
    envelope all key off the same identifier — diffs across
    baselines join cleanly."""
    return BatchEntry(
        task=case.task,
        run_id=case.case_id,  # already minted by parse_cases_file
        cwd=case.cwd,
        timeout_s=case.timeout_s,
        model=case.model,
    )


def _score_case(
    case: EvalCase,
    envelope: dict[str, Any],
    *,
    default_scorer_name: str,
    envelope_path: Path | str,
) -> EvalScore:
    """Score one case's envelope. The case's `scorer` field
    overrides the default; ``actual`` is the envelope's
    `assistant_text`."""
    scorer_name = case.scorer or default_scorer_name
    actual = str(envelope.get("assistant_text", "") or "")
    run_status = str(envelope.get("status", ""))

    if run_status != "ok":
        # The underlying run didn't complete — the scorer
        # can't meaningfully judge an error / timeout /
        # invalid / interrupted result. Surface it as a
        # distinct outcome rather than scoring empty text.
        return EvalScore(
            case_id=case.case_id or "",
            run_id=str(envelope.get("run_id", "")),
            task_excerpt=excerpt(case.task),
            actual_excerpt=excerpt(actual),
            passed=False,
            score=0.0,
            scorer=scorer_name,
            details=(f"run did not complete (status={run_status!r}); scorer not invoked"),
            run_status=run_status,
            envelope_path=str(envelope_path),
        )

    try:
        scorer = get_scorer(scorer_name)
    except KeyError as e:
        # Unknown scorer name — fail this case loudly rather
        # than guess. The CLI's --scorer validation should
        # have caught a typo'd CLI default before reaching
        # here, so this fires when a case's scorer field
        # is wrong.
        return EvalScore(
            case_id=case.case_id or "",
            run_id=str(envelope.get("run_id", "")),
            task_excerpt=excerpt(case.task),
            actual_excerpt=excerpt(actual),
            passed=False,
            score=0.0,
            scorer=scorer_name,
            details=f"scorer error: {e}",
            run_status=run_status,
            envelope_path=str(envelope_path),
        )

    context = {
        "case_id": case.case_id,
        "run_id": envelope.get("run_id"),
        "task": case.task,
        **case.extras,
    }
    try:
        score = scorer(actual, case.expected, context=context)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "scorer %r raised on case %s: %s",
            scorer_name,
            case.case_id,
            e,
        )
        score = Score(
            passed=False,
            score=0.0,
            details=f"scorer raised {type(e).__name__}: {e}",
        )

    return EvalScore(
        case_id=case.case_id or "",
        run_id=str(envelope.get("run_id", "")),
        task_excerpt=excerpt(case.task),
        actual_excerpt=excerpt(actual),
        passed=score.passed,
        score=score.score,
        scorer=scorer_name,
        details=score.details,
        run_status=run_status,
        envelope_path=str(envelope_path),
    )


def _load_baseline(
    baseline_dir: Path | str,
) -> tuple[str, dict[str, EvalScore]] | None:
    """Read a prior eval's summary + score rows. Returns
    ``(baseline_eval_id, scores_by_case_id)`` or None when the
    baseline dir is missing / unreadable / has no summary.

    The baseline join key is ``case_id`` (stable across runs);
    cases without one can't be matched, so the operator should
    pin case_ids in their JSONL when they want regression
    detection.
    """
    bdir = Path(baseline_dir)
    summary_path = bdir / "eval-summary.json"
    if not summary_path.exists():
        return None
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning(
            "baseline summary at %s unreadable; skipping comparison",
            summary_path,
        )
        return None
    baseline_id = str(data.get("eval_id", "unknown"))
    cases_by_id: dict[str, EvalScore] = {}
    for row in data.get("cases", []):
        cid = row.get("case_id")
        if not cid:
            continue
        cases_by_id[cid] = EvalScore(
            case_id=cid,
            run_id=str(row.get("run_id", "")),
            task_excerpt=str(row.get("task_excerpt", "")),
            actual_excerpt=str(row.get("actual_excerpt", "")),
            passed=bool(row.get("passed")),
            score=float(row.get("score", 0.0)),
            scorer=str(row.get("scorer", "")),
            details=str(row.get("details", "")),
            run_status=str(row.get("run_status", "")),
            envelope_path=str(row.get("envelope_path", "")),
        )
    return baseline_id, cases_by_id


def _diff_against_baseline(
    current: list[EvalScore],
    baseline: dict[str, EvalScore],
) -> tuple[list[str], list[str]]:
    """Return (regressions, improvements) — case_ids that
    flipped state between baseline and current.

    Regressions: passed in baseline AND failed (or errored)
    now. Improvements: failed/errored in baseline AND passes
    now. Cases without a stable case_id can't be matched.
    """
    regressions: list[str] = []
    improvements: list[str] = []
    for cs in current:
        cid = cs.case_id
        if not cid or cid not in baseline:
            continue
        bs = baseline[cid]
        was_passing = bs.passed
        now_passing = cs.passed
        if was_passing and not now_passing:
            regressions.append(cid)
        elif not was_passing and now_passing:
            improvements.append(cid)
    return regressions, improvements


def run_eval(
    cases: list[EvalCase],
    *,
    cfg: Config,
    workspace_default: Path,
    output_dir: Path,
    default_scorer: str = "exact",
    eval_id: str | None = None,
    baseline_dir: Path | str | None = None,
    force: bool = False,
    batch_progress: Callable[[Any, int, int], None] | None = None,
    score_progress: ProgressFn | None = None,
    _run_fn: Any = None,
) -> EvalSummary:
    """Execute an eval end-to-end.

    Composes :func:`athena.batch.runner.batch_run` with a
    scoring pass over each per-run envelope.

    Resume-safety: pre-existing per-run envelopes are SKIPPED
    by the batch (the existing assistant_text is re-scored
    cheaply); ``force=True`` re-runs them. Re-scoring is
    always cheap so we don't gate the scoring pass on
    skip/run.

    Returns an :class:`EvalSummary` and writes
    ``<output_dir>/eval-summary.json`` +
    ``<output_dir>/scores.jsonl``.
    """
    eid = eval_id or mint_eval_id()
    started = _now_iso()
    t0 = time.monotonic()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Mint case_ids for cases that don't have one so the batch
    # writes <output_dir>/e-<uuid12>.json (and so the
    # --baseline diff has stable keys to join on).
    for c in cases:
        if not c.case_id:
            c.case_id = mint_case_id()

    # Validate the default scorer exists up front — a typo'd
    # --scorer NAME should fail fast.
    _ = get_scorer(default_scorer)

    # Phase 1: batch through the headless primitive.
    batch_entries = [_case_to_batch_entry(c) for c in cases]
    batch_manifest: BatchManifest = batch_run(
        batch_entries,
        cfg=cfg,
        workspace_default=workspace_default,
        output_dir=output_dir,
        force=force,
        progress=batch_progress,
        run_fn=_run_fn,
    )

    # Phase 2: score each case's envelope.
    cases_by_id = {c.case_id: c for c in cases}
    scored: list[EvalScore] = []
    for idx, c in enumerate(cases, start=1):
        # case_id is minted above for every case that lacked one, so it is
        # non-None here; assert to narrow str | None -> str for mypy.
        assert c.case_id is not None
        envelope_path = output_dir / f"{_safe_filename(c.case_id)}.json"
        if not envelope_path.exists():
            # Defensive: shouldn't happen in the normal flow
            # (batch_run wrote it), but a manifest_only edge
            # case might have skipped writing. Surface as
            # error rather than crash.
            scored.append(
                EvalScore(
                    case_id=c.case_id,
                    run_id="",
                    task_excerpt=excerpt(c.task),
                    actual_excerpt="",
                    passed=False,
                    score=0.0,
                    scorer=c.scorer or default_scorer,
                    details=f"per-run envelope not found at {envelope_path}",
                    run_status="missing",
                    envelope_path=str(envelope_path),
                )
            )
            if score_progress is not None:
                score_progress(scored[-1], idx, len(cases))
            continue

        try:
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            scored.append(
                EvalScore(
                    case_id=c.case_id,
                    run_id="",
                    task_excerpt=excerpt(c.task),
                    actual_excerpt="",
                    passed=False,
                    score=0.0,
                    scorer=c.scorer or default_scorer,
                    details=f"envelope unreadable: {type(e).__name__}: {e}",
                    run_status="missing",
                    envelope_path=str(envelope_path),
                )
            )
            if score_progress is not None:
                score_progress(scored[-1], idx, len(cases))
            continue

        es = _score_case(
            c,
            envelope,
            default_scorer_name=default_scorer,
            envelope_path=envelope_path,
        )
        scored.append(es)
        if score_progress is not None:
            score_progress(es, idx, len(cases))

    # Aggregate.
    total = len(scored)
    passed = sum(1 for s in scored if s.passed)
    failed = sum(1 for s in scored if not s.passed and s.run_status == "ok")
    errored = sum(1 for s in scored if s.run_status not in ("ok", ""))
    pass_rate = (passed / total) if total else 0.0
    avg_score = sum(s.score for s in scored) / total if total else 0.0
    by_scorer: dict[str, dict[str, int]] = {}
    for s in scored:
        bucket = by_scorer.setdefault(
            s.scorer,
            {"total": 0, "passed": 0, "failed": 0, "errored": 0},
        )
        bucket["total"] += 1
        if s.passed:
            bucket["passed"] += 1
        elif s.run_status == "ok":
            bucket["failed"] += 1
        else:
            bucket["errored"] += 1

    summary = EvalSummary(
        eval_id=eid,
        batch_id=batch_manifest.batch_id,
        started_at=started,
        finished_at=_now_iso(),
        duration_s=time.monotonic() - t0,
        output_dir=str(output_dir),
        total=total,
        passed=passed,
        failed=failed,
        errored=errored,
        pass_rate=pass_rate,
        avg_score=avg_score,
        by_scorer=by_scorer,
        cases=scored,
    )

    # Baseline diff (optional).
    if baseline_dir is not None:
        bl = _load_baseline(baseline_dir)
        if bl is not None:
            baseline_id, baseline_scores = bl
            regressions, improvements = _diff_against_baseline(
                scored,
                baseline_scores,
            )
            summary.baseline_id = baseline_id
            summary.regressions = regressions
            summary.improvements = improvements
        else:
            logger.warning(
                "baseline_dir=%s has no readable eval-summary.json; skipping comparison",
                baseline_dir,
            )

    # Persist artifacts.
    (output_dir / "eval-summary.json").write_text(
        summary.to_json(indent=2),
        encoding="utf-8",
    )
    (output_dir / "scores.jsonl").write_text(
        "\n".join(json.dumps(s.to_dict(), ensure_ascii=False) for s in scored) + "\n",
        encoding="utf-8",
    )
    return summary
