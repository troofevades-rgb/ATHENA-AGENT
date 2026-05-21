"""``athena eval <cases.jsonl>`` — eval battery CLI (T7-03.3).

Closes the trio T7-01 / T7-02 / T7-03. Composes T7-02 batch
with a scoring pass; optional baseline regression diff.

Per-case envelopes + eval-summary.json + scores.jsonl land in
``--output-dir`` (default ``<profile>/eval/<eval_id>/``).
Progress lines on stderr; ``--json`` puts the final summary on
stdout (single-line) for piping. Exit code 0 when every case
passes, 1 on any failure, 2 on validation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..config import load_config, profile_dir


def _build_parser() -> argparse.ArgumentParser:
    from ..eval.scorers import list_scorers

    scorers_blurb = ", ".join(list_scorers())
    p = argparse.ArgumentParser(
        prog="athena eval",
        description=(
            "Run a labeled case set through athena's batch + "
            "scoring pipeline. Per-case envelopes + a scored "
            "summary land in --output-dir. CI exit-code gates "
            "(0 = all passed, 1 = any failed, 2 = validation)."
        ),
    )
    p.add_argument("cases_file", help="Path to the eval cases JSONL.")
    p.add_argument(
        "--output-dir", "-o",
        help=(
            "Where to write per-run envelopes + scores.jsonl "
            "+ eval-summary.json. Default <profile>/eval/<eval_id>/."
        ),
    )
    p.add_argument(
        "--eval-id",
        help="Operator-supplied eval ID. Auto-minted as v-<uuid12> otherwise.",
    )
    p.add_argument(
        "--scorer",
        default="exact",
        help=(
            f"Default scorer for cases without their own. "
            f"Available: {scorers_blurb}. Default: exact."
        ),
    )
    p.add_argument(
        "--baseline",
        help=(
            "Path to a prior eval's output dir (containing "
            "eval-summary.json). The current run will compute "
            "regressions (passed there, failed here) and "
            "improvements (failed there, passes here), joined "
            "by case_id."
        ),
    )
    p.add_argument(
        "--force",
        action="store_true",
        help=(
            "Re-run every case even if its envelope already "
            "exists in --output-dir. Default is resume-safe "
            "(reuse existing envelopes + re-score)."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit the final eval summary as a single-line JSON "
            "document on stdout (in addition to writing it to "
            "disk). Progress lines go to stderr regardless."
        ),
    )
    p.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress per-case progress lines on stderr.",
    )
    p.add_argument(
        "--profile",
        help="Active profile (overrides ATHENA_PROFILE / config).",
    )
    p.add_argument(
        "--cwd", "-C",
        help="Default workspace for cases without their own cwd.",
    )
    return p


def _resolve_output_dir(
    args: argparse.Namespace, *, eval_id: str, cfg: Any,
) -> Path:
    if args.output_dir:
        return Path(args.output_dir).expanduser()
    profile = getattr(args, "profile", None) or cfg.profile or "default"
    return profile_dir(profile) / "eval" / eval_id


def _score_progress_to_stderr(quiet: bool):
    """Per-case progress emitter. Mirrors batch's stderr lines
    but adds the passed/failed mark + scorer name."""
    if quiet:
        return None

    def _print(es, done: int, total: int) -> None:
        mark = "PASS" if es.passed else (
            "ERR " if es.run_status not in ("ok", "") else "FAIL"
        )
        sys.stderr.write(
            f"[{done:>4}/{total}] {mark}  {es.case_id}  "
            f"scorer={es.scorer}  {es.task_excerpt[:60]}\n"
        )
        sys.stderr.flush()

    return _print


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)

    cfg = load_config()
    if args.profile:
        cfg.profile = args.profile

    workspace = (
        Path(args.cwd).expanduser().resolve() if args.cwd else Path.cwd().resolve()
    )
    if not workspace.is_dir():
        sys.stderr.write(f"eval: workspace not a directory: {workspace}\n")
        return 2

    # Validate the default scorer before doing anything else
    # so a typo'd --scorer NAME fails fast.
    from ..eval.scorers import get_scorer, list_scorers
    try:
        get_scorer(args.scorer)
    except KeyError as e:
        sys.stderr.write(
            f"eval: {e}\n"
            f"      available scorers: {', '.join(list_scorers())}\n"
        )
        return 2

    try:
        from ..eval.runner import parse_cases_file
        cases = parse_cases_file(args.cases_file)
    except FileNotFoundError as e:
        sys.stderr.write(f"eval: {e}\n")
        return 2
    except ValueError as e:
        sys.stderr.write(f"eval: {e}\n")
        return 2

    from ..eval.summary import mint_eval_id
    eid = args.eval_id or mint_eval_id()
    output_dir = _resolve_output_dir(args, eval_id=eid, cfg=cfg)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not cases:
        sys.stderr.write("eval: cases file has no entries\n")
        # Still write an empty summary so CI can read it.
        from ..eval.summary import EvalSummary
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        summary = EvalSummary(
            eval_id=eid, batch_id="", started_at=now, finished_at=now,
            duration_s=0.0, output_dir=str(output_dir),
            total=0, passed=0, failed=0, errored=0,
            pass_rate=0.0, avg_score=0.0,
        )
        (output_dir / "eval-summary.json").write_text(
            summary.to_json(indent=2), encoding="utf-8",
        )
        if args.json:
            sys.stdout.write(summary.to_json(indent=None) + "\n")
        return 0

    score_progress = _score_progress_to_stderr(args.quiet)

    from ..eval.runner import run_eval
    summary = run_eval(
        cases,
        cfg=cfg,
        workspace_default=workspace,
        output_dir=output_dir,
        default_scorer=args.scorer,
        eval_id=eid,
        baseline_dir=args.baseline,
        force=args.force,
        score_progress=score_progress,
    )

    if args.json:
        sys.stdout.write(summary.to_json(indent=None) + "\n")
        sys.stdout.flush()
    else:
        # Human-friendly summary.
        sys.stderr.write(
            f"\neval {summary.eval_id}: "
            f"{summary.passed}/{summary.total} passed "
            f"({summary.pass_rate * 100:.1f}%), "
            f"{summary.failed} failed, {summary.errored} errored\n"
        )
        if summary.baseline_id is not None:
            sys.stderr.write(
                f"baseline {summary.baseline_id}: "
                f"{len(summary.regressions)} regression(s), "
                f"{len(summary.improvements)} improvement(s)\n"
            )
            if summary.regressions:
                sys.stderr.write(
                    f"  regressed: {', '.join(summary.regressions)}\n"
                )
            if summary.improvements:
                sys.stderr.write(
                    f"  improved:  {', '.join(summary.improvements)}\n"
                )
        sys.stderr.write(
            f"summary: {output_dir / 'eval-summary.json'}\n"
        )

    # Exit code: 0 if every case passed; 1 if any failed or
    # errored; 2 already returned above for validation.
    return 0 if (summary.failed == 0 and summary.errored == 0) else 1
