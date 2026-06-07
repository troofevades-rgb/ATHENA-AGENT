"""``athena eval`` — two eval surfaces under one CLI.

Subcommands:

  ``athena eval text <cases.jsonl>``
        Text-output evaluation (T7-03). Scores ``assistant_text``
        against an ``expected`` string/regex/json-path per case.
        Best for QA-style benchmarks where the right answer is in
        the model's reply.

  ``athena eval run --tasks <set>``
        Tool-calling capability evaluation. Verifies what the agent
        actually DID (filesystem state, MCP call log, etc.) by
        running each task in an isolated tempdir and calling its
        per-task ``verify_fn``. Best for "does this LoRA actually
        do better tool-calling than the base?"

  ``athena eval compare <a.json> <b.json>``
        Diff two capability reports (regressions / improvements /
        delta pass-rate).

  ``athena eval list-tasks [--bucket NAME]``
        List the catalog of agent tasks.

Back-compat: ``athena eval <cases.jsonl>`` (positional file as the
first argument) is still accepted as an alias for ``athena eval text``
to keep older scripts working.

Per-case envelopes + eval-summary.json + scores.jsonl land in
``--output-dir`` (default ``<profile>/eval/<eval_id>/`` for text;
``<profile>/eval/agent/<timestamp>.json`` for the agent eval).
Progress lines on stderr; ``--json`` puts the final summary on
stdout (single-line) for piping. Exit code 0 when every case
passes, 1 on any failure, 2 on validation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import load_config, profile_dir

if TYPE_CHECKING:
    from ..eval.agent.report import TaskResult
    from ..eval.runner import ProgressFn
    from ..eval.summary import EvalScore


def _build_parser() -> argparse.ArgumentParser:
    """Builds the parser for the TEXT-EVAL subcommand only.

    The main ``athena eval`` dispatcher (see ``main()`` below) picks
    between the text-eval / agent-eval / compare / list-tasks
    surfaces BEFORE this parser is consulted.
    """
    from ..eval.scorers import list_scorers

    scorers_blurb = ", ".join(list_scorers())
    p = argparse.ArgumentParser(
        prog="athena eval text",
        description=(
            "Run a labeled case set through athena's batch + "
            "scoring pipeline. Per-case envelopes + a scored "
            "summary land in --output-dir. CI exit-code gates "
            "(0 = all passed, 1 = any failed, 2 = validation)."
        ),
    )
    p.add_argument("cases_file", help="Path to the eval cases JSONL.")
    p.add_argument(
        "--output-dir",
        "-o",
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
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress per-case progress lines on stderr.",
    )
    p.add_argument(
        "--profile",
        help="Active profile (overrides ATHENA_PROFILE / config).",
    )
    p.add_argument(
        "--cwd",
        "-C",
        help="Default workspace for cases without their own cwd.",
    )
    return p


def _resolve_output_dir(
    args: argparse.Namespace,
    *,
    eval_id: str,
    cfg: Any,
) -> Path:
    if args.output_dir:
        return Path(args.output_dir).expanduser()
    profile = getattr(args, "profile", None) or cfg.profile or "default"
    return profile_dir(profile) / "eval" / eval_id


def _score_progress_to_stderr(quiet: bool) -> ProgressFn | None:
    """Per-case progress emitter. Mirrors batch's stderr lines
    but adds the passed/failed mark + scorer name."""
    if quiet:
        return None

    def _print(es: EvalScore, done: int, total: int) -> None:
        mark = "PASS" if es.passed else ("ERR " if es.run_status not in ("ok", "") else "FAIL")
        sys.stderr.write(
            f"[{done:>4}/{total}] {mark}  {es.case_id}  "
            f"scorer={es.scorer}  {es.task_excerpt[:60]}\n"
        )
        sys.stderr.flush()

    return _print


def _main_text(argv: list[str]) -> int:
    """Existing T7-03 text-eval entry point.

    Wired through ``main()`` below as the ``text`` subcommand and as
    the back-compat fallback when no subcommand is given but a
    positional cases-file IS.
    """
    args = _build_parser().parse_args(argv)

    cfg = load_config()
    if args.profile:
        cfg.profile = args.profile

    workspace = Path(args.cwd).expanduser().resolve() if args.cwd else Path.cwd().resolve()
    if not workspace.is_dir():
        sys.stderr.write(f"eval: workspace not a directory: {workspace}\n")
        return 2

    # Validate the default scorer before doing anything else
    # so a typo'd --scorer NAME fails fast.
    from ..eval.scorers import get_scorer, list_scorers

    try:
        get_scorer(args.scorer)
    except KeyError as e:
        sys.stderr.write(f"eval: {e}\n      available scorers: {', '.join(list_scorers())}\n")
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
        import datetime

        from ..eval.summary import EvalSummary

        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        summary = EvalSummary(
            eval_id=eid,
            batch_id="",
            started_at=now,
            finished_at=now,
            duration_s=0.0,
            output_dir=str(output_dir),
            total=0,
            passed=0,
            failed=0,
            errored=0,
            pass_rate=0.0,
            avg_score=0.0,
        )
        (output_dir / "eval-summary.json").write_text(
            summary.to_json(indent=2),
            encoding="utf-8",
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
                sys.stderr.write(f"  regressed: {', '.join(summary.regressions)}\n")
            if summary.improvements:
                sys.stderr.write(f"  improved:  {', '.join(summary.improvements)}\n")
        sys.stderr.write(f"summary: {output_dir / 'eval-summary.json'}\n")

    # Exit code: 0 if every case passed; 1 if any failed or
    # errored; 2 already returned above for validation.
    return 0 if (summary.failed == 0 and summary.errored == 0) else 1


# ---------------------------------------------------------------------------
# Agent-eval: ``athena eval run``
# ---------------------------------------------------------------------------


def _build_run_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="athena eval run",
        description=(
            "Run the agent capability eval. Each task runs in an "
            "isolated tempdir; verify_fn inspects post-run state. "
            "Reports a single pass-rate for the (model, policy, "
            "task_set) tuple."
        ),
    )
    p.add_argument(
        "--model",
        required=True,
        help="Model tag passed to the Agent (e.g. troofevades-q35:athena).",
    )
    p.add_argument(
        "--tasks",
        default="default",
        help=(
            "Task-set name. Built-ins: default, file_ops, shell, "
            "structured, mcp. User-supplied modules under "
            "~/.athena/eval_tasks/ are also addressable by filename "
            "(without .py). Default: 'default'."
        ),
    )
    p.add_argument(
        "--policy",
        choices=("default", "static", "heuristic"),
        default="default",
        help=(
            "Parseltongue policy. 'default' uses the active config "
            "(usually heuristic); 'static' opts out (no param "
            "overrides); 'heuristic' forces the rule-based policy."
        ),
    )
    p.add_argument(
        "--output",
        "-o",
        required=True,
        help="Path to write the JSON report.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="If >0, only run the first N tasks (smoke-testing).",
    )
    p.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress per-task progress on stderr.",
    )
    return p


def _main_run(argv: list[str]) -> int:
    args = _build_run_parser().parse_args(argv)

    from ..eval.agent.runner import run_eval
    from ..eval.agent.tasks.default import get_task_set

    try:
        tasks = get_task_set(args.tasks)
    except KeyError as e:
        sys.stderr.write(f"eval run: {e}\n")
        return 2

    if args.limit and args.limit > 0:
        tasks = tasks[: args.limit]

    if not tasks:
        sys.stderr.write(f"eval run: task set {args.tasks!r} is empty\n")
        return 2

    policy_config: dict[str, Any] | None
    if args.policy == "default":
        policy_config = None
    elif args.policy == "static":
        policy_config = {"policy": "static", "defaults": {}}
    else:
        policy_config = {"policy": "heuristic"}

    def _progress(msg: str) -> None:
        if not args.quiet:
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()

    def _on_task_done(result: TaskResult) -> None:
        if args.quiet:
            return
        mark = {
            "passed": "PASS",
            "failed": "FAIL",
            "timeout": "TOUT",
            "error": "ERR ",
        }.get(result.status, "????")
        sys.stderr.write(
            f"  {mark}  {result.task_id}  ({result.duration_s:.1f}s, "
            f"{result.turns}t/{result.tool_calls}tc)\n"
        )
        sys.stderr.flush()

    report = run_eval(
        tasks,
        model=args.model,
        policy_config=policy_config,
        task_set_name=args.tasks,
        on_progress=_progress,
        on_task_done=_on_task_done,
    )

    out_path = Path(args.output).expanduser().resolve()
    report.write_json(out_path)

    if not args.quiet:
        sys.stderr.write(
            f"\neval run: {report.passed}/{report.total} passed ({report.pass_rate * 100:.1f}%)"
        )
        if report.failed or report.timed_out or report.errored:
            sys.stderr.write(
                f"  [{report.failed} failed, {report.timed_out} timeout, {report.errored} error]"
            )
        sys.stderr.write(f"\nreport: {out_path}\n")
        # Per-bucket breakdown.
        by_bucket = report.by_bucket()
        if len(by_bucket) > 1:
            for name, stats in sorted(by_bucket.items()):
                sys.stderr.write(
                    f"  {name:>10}: {stats['passed']}/{stats['total']} "
                    f"({stats['pass_rate'] * 100:.0f}%)\n"
                )

    # CI exit: 0 if every task passed, 1 otherwise.
    return 0 if report.pass_rate == 1.0 else 1


# ---------------------------------------------------------------------------
# Diff two reports: ``athena eval compare``
# ---------------------------------------------------------------------------


def _build_compare_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="athena eval compare",
        description=(
            "Diff two agent-eval reports. Reports cases that "
            "regressed (passed-then-failed) and improved "
            "(failed-then-passed). Exit 0 if no regressions; 1 "
            "if any regressed."
        ),
    )
    p.add_argument("baseline", help="Path to baseline report JSON.")
    p.add_argument("current", help="Path to current report JSON.")
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit the diff as JSON on stdout instead of human text.",
    )
    return p


def _main_compare(argv: list[str]) -> int:
    args = _build_compare_parser().parse_args(argv)

    from ..eval.agent.report import EvalReport, compare_reports

    base_path = Path(args.baseline).expanduser()
    cur_path = Path(args.current).expanduser()

    for label, path in (("baseline", base_path), ("current", cur_path)):
        if not path.exists():
            sys.stderr.write(f"eval compare: {label} not found: {path}\n")
            return 2

    try:
        base = EvalReport.from_dict(json.loads(base_path.read_text(encoding="utf-8")))
        cur = EvalReport.from_dict(json.loads(cur_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        sys.stderr.write(f"eval compare: malformed report: {e}\n")
        return 2

    diff = compare_reports(base, cur)

    if args.json:
        sys.stdout.write(json.dumps(diff.to_dict(), indent=None) + "\n")
        return 1 if diff.regressions else 0

    # Human-friendly.
    delta_sign = "+" if diff.delta_pass_rate >= 0 else ""
    sys.stderr.write(
        f"baseline ({diff.baseline_model}): "
        f"{diff.baseline_pass_rate * 100:.1f}%\n"
        f"current  ({diff.current_model}):  "
        f"{diff.current_pass_rate * 100:.1f}% "
        f"(Δ{delta_sign}{diff.delta_pass_rate * 100:.1f}pp)\n"
    )
    sys.stderr.write(
        f"regressions: {len(diff.regressions)}   "
        f"improvements: {len(diff.improvements)}   "
        f"unchanged: {len(diff.unchanged_pass) + len(diff.unchanged_fail)}\n"
    )
    if diff.regressions:
        sys.stderr.write("  regressed: " + ", ".join(diff.regressions) + "\n")
    if diff.improvements:
        sys.stderr.write("  improved:  " + ", ".join(diff.improvements) + "\n")
    if diff.only_in_baseline:
        sys.stderr.write("  only_in_baseline: " + ", ".join(diff.only_in_baseline) + "\n")
    if diff.only_in_current:
        sys.stderr.write("  only_in_current:  " + ", ".join(diff.only_in_current) + "\n")

    return 1 if diff.regressions else 0


# ---------------------------------------------------------------------------
# Catalog listing: ``athena eval list-tasks``
# ---------------------------------------------------------------------------


def _build_list_tasks_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="athena eval list-tasks",
        description="Print the catalog of agent-eval tasks.",
    )
    p.add_argument(
        "--bucket",
        help=(
            "Filter to one bucket (file_ops, shell, structured, mcp) "
            "or one user-defined task-set name. Default: show all."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit as JSON instead of human-readable table.",
    )
    return p


def _main_list_tasks(argv: list[str]) -> int:
    args = _build_list_tasks_parser().parse_args(argv)
    from ..eval.agent.tasks.default import BUCKETS, get_task_set

    if args.bucket:
        try:
            tasks = get_task_set(args.bucket)
        except KeyError as e:
            sys.stderr.write(f"eval list-tasks: {e}\n")
            return 2
        groups = {args.bucket: tasks}
    else:
        # Default view: every built-in bucket EXCEPT "default" (which
        # is just the union — would double-count).
        groups = {k: v for k, v in BUCKETS.items() if k != "default"}

    if args.json:
        out = {name: [t.to_catalog_dict() for t in tasks] for name, tasks in groups.items()}
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return 0

    total = sum(len(g) for g in groups.values())
    sys.stdout.write(f"{total} task(s) across {len(groups)} bucket(s):\n\n")
    for name, tasks in groups.items():
        sys.stdout.write(f"[{name}] ({len(tasks)} tasks)\n")
        for t in tasks:
            mcp_tag = " [mcp]" if t.mcp_servers else ""
            sys.stdout.write(f"  {t.id:35s}{mcp_tag}  {t.short_description()}\n")
        sys.stdout.write("\n")
    return 0


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


_SUBCOMMANDS = {
    "text": _main_text,
    "run": _main_run,
    "compare": _main_compare,
    "list-tasks": _main_list_tasks,
}


def main(argv: list[str]) -> int:
    """Top-level dispatcher.

    Routes to ``_main_text``, ``_main_run``, ``_main_compare``, or
    ``_main_list_tasks`` based on ``argv[0]``. For back-compat, if
    the first argument doesn't match any subcommand name (e.g.
    ``athena eval cases.jsonl`` from older scripts), falls through
    to the text-eval handler with argv unchanged.
    """
    if not argv:
        sys.stderr.write(
            "usage: athena eval {text,run,compare,list-tasks} [options]\n"
            "\n"
            "Subcommands:\n"
            "  text       Score text outputs against expected strings (T7-03)\n"
            "  run        Run the agent capability eval (tool-calling tasks)\n"
            "  compare    Diff two agent-eval reports\n"
            "  list-tasks Print the agent-eval task catalog\n"
            "\n"
            "Back-compat: 'athena eval <cases.jsonl>' still routes to 'text'.\n"
        )
        return 2

    head = argv[0]
    if head in _SUBCOMMANDS:
        return _SUBCOMMANDS[head](argv[1:])
    # Back-compat: first arg is a path / unknown flag — assume legacy
    # text-eval invocation (``athena eval cases.jsonl``).
    return _main_text(argv)
