"""``athena train {review,build-dataset,run,status}`` — closed training loop.

Subcommand contracts:

- ``review``: interactive trajectory labeling for sessions in the last
  ``--since-days`` (default 30). Persists labels to
  ``<profile_dir>/labels/<session_id>.json``.
- ``build-dataset``: walks every session in the window, builds SFT and
  DPO JSONL files and writes them to ``transform/datasets/<sft|dpo>-
  <timestamp>.jsonl``. Returns the two paths.
- ``run``: orchestrates LoRA → DPO (if a DPO dataset was passed or
  produced) → GGUF export → ``ollama create``. Output name defaults to
  ``<base>-athena-<n>`` where ``n`` is the next free index.
- ``status``: prints the last training run's metadata from
  ``~/.athena/training_state.json``.

State file:
    ``~/.athena/training_state.json`` holds an array of past runs.
    {"runs": [{"timestamp", "base_model", "output_name", "output_dir",
               "sft_dataset", "dpo_dataset", "exit_codes": {...}}]}
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import CONFIG_DIR
from ..config import profile_dir as _profile_dir
from ..sessions.store import SessionStore
from ..transform.classifier import Trajectory, auto_classify, extract_trajectories
from ..transform.dataset import (
    build_dpo_dataset_from_trajectories,
    build_sft_dataset,
    write_jsonl,
)
from ..transform.review import ReviewSession, default_prompt, load_labels
from ..transform.run_state import (
    RunState,
    find_latest_checkpoint,
)
from ..transform.run_state import (
    load as load_run_state,
)
from ..transform.runner import (
    TrainingRun,
    ensure_ollama_on_path,
    export_to_gguf,
    find_lora_adapter,
    run_dpo,
    run_lora,
)

TRAINING_STATE_PATH = CONFIG_DIR / "training_state.json"


# ---- State helpers -----------------------------------------------------


def _load_state() -> dict[str, Any]:
    if not TRAINING_STATE_PATH.exists():
        return {"runs": []}
    try:
        data = json.loads(TRAINING_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"runs": []}
    if not isinstance(data, dict) or "runs" not in data:
        return {"runs": []}
    return data


def _save_state(state: dict[str, Any]) -> None:
    TRAINING_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRAINING_STATE_PATH.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _next_output_name(base_model: str) -> str:
    state = _load_state()
    base_tag = base_model.split("/")[-1]  # strip HF org prefix
    used = {
        r.get("output_name") for r in state.get("runs", []) if isinstance(r.get("output_name"), str)
    }
    n = 1
    while f"{base_tag}-athena-{n}" in used:
        n += 1
    return f"{base_tag}-athena-{n}"


# ---- Subcommand handlers ----------------------------------------------


def _cmd_review(args: argparse.Namespace) -> int:
    profile_dir = _profile_dir(args.profile)
    if getattr(args, "no_tui", False):
        return _cmd_review_classic(profile_dir, args)
    # T3-05R: textual TUI is the default. Falls back to the classic
    # one-at-a-time prompt if textual isn't installed (athena[train]
    # extra not present).
    try:
        from ..transform.review_tui import run_review_tui
        from ..transform.suggestion import build_suggestion_fn

        suggestion_fn = build_suggestion_fn(profile_dir)
        return run_review_tui(
            profile_dir=profile_dir,
            since_days=args.since_days,
            keymap=getattr(args, "keymap", "default"),
            suggestion_fn=suggestion_fn,
        )
    except RuntimeError as e:
        # textual missing — fall back to classic with a hint
        print(f"note: {e}\nfalling back to --no-tui mode.\n")
        return _cmd_review_classic(profile_dir, args)


def _cmd_review_classic(profile_dir: Path, args: argparse.Namespace) -> int:
    """The pre-T3-05R one-at-a-time prompt path. Reached via
    --no-tui or when textual isn't installed."""
    review = ReviewSession(profile_dir, since_days=args.since_days)
    try:
        progress = review.start(default_prompt)
    finally:
        review.close()
    print(
        f"\nreviewed {progress.seen} trajectory(ies): "
        f"{progress.labeled} labeled, {progress.skipped} skipped"
        + (" (quit early)" if progress.quit_early else "")
    )
    return 0


def _enumerate_trajectories(
    profile_dir: Path, since_days: int, include_auto_labels: bool
) -> Iterator[Trajectory]:
    """Yield Trajectories from every recent session, with user_label hydrated."""
    from datetime import timedelta

    store = SessionStore(profile_dir)
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        sessions = store.list_sessions(limit=10_000)
        for meta in sessions:
            if meta.started_at < cutoff:
                continue
            try:
                messages = list(store.load(meta.session_id))
            except (OSError, FileNotFoundError):
                continue
            existing = load_labels(profile_dir, meta.session_id)
            trajectories = extract_trajectories(meta.session_id, messages)
            for idx, t in enumerate(trajectories):
                nxt = None
                if idx + 1 < len(trajectories):
                    for m in trajectories[idx + 1].turns:
                        if m.get("role") == "user":
                            nxt = m
                            break
                t.auto_label = auto_classify(t, next_user_message=nxt)
                key = f"{t.turn_start}-{t.turn_end}"
                if key in existing:
                    t.user_label = existing[key]  # type: ignore[assignment]
                yield t
    finally:
        store.close()


def _cmd_build_dataset(args: argparse.Namespace) -> int:
    profile_dir = _profile_dir(args.profile)
    trajectories = list(
        _enumerate_trajectories(
            profile_dir,
            args.since_days,
            args.include_auto_labels,
        )
    )
    if not trajectories:
        print("(no trajectories in window)", file=sys.stderr)
        return 1

    sft = build_sft_dataset(
        trajectories,
        chat_template=args.chat_template,
        include_auto_labels=args.include_auto_labels,
    )
    # DPO pair extraction: each ``preference_pair`` trajectory is split
    # at its ``[/steer]`` marker into a (prompt, chosen, rejected) example
    # where pre-steer assistant work is the rejected branch and post-steer
    # recovery is the chosen branch. Both share the same prompt — the DPO
    # invariant the previous cross-trajectory pairing violated.
    dpo = build_dpo_dataset_from_trajectories(
        trajectories,
        chat_template=args.chat_template,
        include_auto_labels=args.include_auto_labels,
    )

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    sft_path = output_dir / f"sft-{ts}.jsonl"
    dpo_path = output_dir / f"dpo-{ts}.jsonl"

    if sft:
        write_jsonl(sft_path, sft)
        print(f"wrote {len(sft)} SFT examples -> {sft_path}")
    else:
        print("(no good-labeled trajectories - SFT file not written)", file=sys.stderr)

    if dpo:
        write_jsonl(dpo_path, dpo)
        print(f"wrote {len(dpo)} DPO pairs -> {dpo_path}")
        # Emit a one-line breakdown of failure modes — useful for telling
        # whether the dataset is dominated by one kind of error (which
        # would skew DPO toward fixing only that pattern).
        from collections import Counter

        modes = Counter(ex["metadata"].get("failure_mode", "other") for ex in dpo)
        breakdown = ", ".join(f"{m}={n}" for m, n in modes.most_common())
        print(f"  failure modes: {breakdown}")
    else:
        print("(no preference pairs found - DPO file not written)", file=sys.stderr)

    return 0 if sft or dpo else 1


def _cmd_run(args: argparse.Namespace) -> int:
    """Run the LoRA -> DPO -> GGUF pipeline, persisting per-phase state
    to ``<output_dir>/.athena_train_state.json``.

    With ``--resume`` (or when invoked via ``athena train resume``), an
    existing state file is loaded, ``completed`` phases are skipped,
    and ``failed`` or interrupted phases are retried — for SFT
    specifically, the retry passes the latest HF checkpoint through
    so HF Trainer restores step / optimizer / scheduler state rather
    than starting from zero.
    """
    if not args.sft_dataset:
        print("error: --sft-dataset is required", file=sys.stderr)
        return 2
    sft_dataset = Path(args.sft_dataset).expanduser().resolve()
    if not sft_dataset.exists():
        print(f"error: SFT dataset not found: {sft_dataset}", file=sys.stderr)
        return 2

    dpo_dataset = Path(args.dpo_dataset).expanduser().resolve() if args.dpo_dataset else None
    if dpo_dataset and not dpo_dataset.exists():
        print(f"warning: DPO dataset not found: {dpo_dataset}; skipping DPO", file=sys.stderr)
        dpo_dataset = None

    output_name = args.output_name or _next_output_name(args.base_model)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else (Path("transform") / "output" / output_name).resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = output_dir / "checkpoints"

    export_ok = ensure_ollama_on_path()
    state = _load_or_create_state(
        output_dir=output_dir,
        run_id=output_name,
        args=args,
        dpo_enabled=dpo_dataset is not None,
        export_enabled=export_ok,
        resume=getattr(args, "resume", False),
    )
    if state is None:
        # Resume requested but no state file found.
        print(
            f"error: --resume requested but no state file at {output_dir}/.athena_train_state.json",
            file=sys.stderr,
        )
        return 2

    if state.is_complete():
        print(
            f"run {output_name} already complete; nothing to do.\n"
            f"  athena model switch {output_name}   # to make it the default",
        )
        return 0

    if not export_ok and state.status_of("export") != "skipped":
        # ollama disappeared from PATH between runs — skip rather than
        # try and fail.
        print("warning: 'ollama' not on PATH — export phase will be skipped", file=sys.stderr)
        state.skip_phase("export")
        state.save()

    run = TrainingRun(
        base_model=args.base_model,
        sft_dataset=sft_dataset,
        dpo_dataset=dpo_dataset,
        output_dir=output_dir,
        checkpoint_dir=checkpoint_dir,
        epochs=args.epochs,
        learning_rate=args.lr,
        lora_rank=args.lora_rank,
    )

    # ---- Phase: SFT ----
    if state.needs_run("sft"):
        # If a prior attempt left a checkpoint behind, resume from it.
        # We re-scan the filesystem rather than trust the state file
        # alone — the user may have manually deleted a corrupt
        # checkpoint, and the most recent valid one on disk is what
        # HF Trainer can actually restore.
        latest_ckpt = find_latest_checkpoint(checkpoint_dir)
        if latest_ckpt is not None:
            print(f"=== Phase 1: SFT (resuming from {latest_ckpt.name})")
            run.resume_from_checkpoint = latest_ckpt
        else:
            print(f"=== Phase 1: LoRA SFT -> {output_dir}")
        state.start_phase("sft")
        state.save()
        rc_sft = run_lora(run)
        if rc_sft != 0:
            # On failure, capture whatever checkpoint did get written —
            # the next resume will pick it up.
            crash_ckpt = find_latest_checkpoint(checkpoint_dir)
            state.fail_phase(
                "sft",
                exit_code=rc_sft,
                error=f"LoRA training exited {rc_sft}",
                checkpoint=str(crash_ckpt) if crash_ckpt else None,
            )
            state.save()
            print(f"error: LoRA training failed (exit {rc_sft})", file=sys.stderr)
            _record_run_legacy(args, output_name, output_dir, sft_dataset, dpo_dataset, state)
            return rc_sft
        # SFT succeeded. If this was a resume that came after a prior
        # failure, downstream completed/failed phases need to re-run
        # against the new adapter — invalidate them.
        reset = state.invalidate_downstream("sft")
        if reset:
            print(f"  (also re-running due to upstream change: {', '.join(reset)})")
        state.complete_phase(
            "sft",
            exit_code=0,
            checkpoint=str(latest_ckpt) if latest_ckpt else None,
        )
        state.save()

    sft_lora = find_lora_adapter(output_dir)
    if sft_lora is None:
        print(f"error: could not locate SFT LoRA adapter under {output_dir}", file=sys.stderr)
        return 1

    # ---- Phase: DPO (soft-fail: warns but continues with SFT-only) ----
    final_lora = sft_lora
    if state.needs_run("dpo"):
        if dpo_dataset is None:
            # The original run didn't have a DPO dataset; the user must
            # have added one on resume. Either way, mark it skipped.
            state.skip_phase("dpo")
            state.save()
        else:
            print("=== Phase 2: DPO on top of SFT LoRA")
            state.start_phase("dpo")
            state.save()
            rc_dpo = run_dpo(run, sft_lora)
            if rc_dpo != 0:
                state.fail_phase(
                    "dpo",
                    exit_code=rc_dpo,
                    error=f"DPO training exited {rc_dpo}",
                )
                state.save()
                print(
                    f"warning: DPO training failed (exit {rc_dpo}); "
                    "proceeding with SFT-only adapter",
                    file=sys.stderr,
                )
            else:
                reset = state.invalidate_downstream("dpo")
                if reset:
                    print(f"  (also re-running due to upstream change: {', '.join(reset)})")
                state.complete_phase("dpo", exit_code=0)
                state.save()
                dpo_out = output_dir.with_name(output_dir.name + "-dpo")
                maybe_dpo_lora = find_lora_adapter(dpo_out)
                if maybe_dpo_lora is not None:
                    final_lora = maybe_dpo_lora

    # If DPO completed previously (this is a fresh resume that didn't
    # touch DPO), still prefer the DPO adapter as the export source.
    if state.status_of("dpo") == "completed" and final_lora is sft_lora:
        dpo_out = output_dir.with_name(output_dir.name + "-dpo")
        maybe_dpo_lora = find_lora_adapter(dpo_out)
        if maybe_dpo_lora is not None:
            final_lora = maybe_dpo_lora

    # ---- Phase: export ----
    if state.needs_run("export"):
        print(f"=== Phase 3: GGUF export + ollama create {output_name}")
        state.start_phase("export")
        state.save()
        rc_export = export_to_gguf(
            final_lora,
            ollama_name=output_name,
            base_model=args.base_model,
        )
        if rc_export != 0:
            state.fail_phase(
                "export",
                exit_code=rc_export,
                error=f"GGUF export exited {rc_export}",
            )
            state.save()
            print(f"error: GGUF export failed (exit {rc_export})", file=sys.stderr)
            _record_run_legacy(args, output_name, output_dir, sft_dataset, dpo_dataset, state)
            return rc_export
        state.complete_phase("export", exit_code=0)
        state.save()

    _record_run_legacy(args, output_name, output_dir, sft_dataset, dpo_dataset, state)
    print(f"\n[ok] training complete. New Ollama model: {output_name}")
    print(f"  athena model switch {output_name}   # to make it the default")
    return 0


def _load_or_create_state(
    *,
    output_dir: Path,
    run_id: str,
    args: argparse.Namespace,
    dpo_enabled: bool,
    export_enabled: bool,
    resume: bool,
) -> RunState | None:
    """Either load an existing state file (resume path) or create a new one.

    Returns ``None`` when ``resume=True`` was passed but no state file
    exists at ``output_dir`` — the caller surfaces that as a user error
    so a typo in ``--output-dir`` doesn't silently start a fresh run.
    """
    existing = load_run_state(output_dir)
    if resume:
        if existing is None:
            return None
        # Refresh the gate flags in case the user supplied different
        # ``--dpo-dataset`` / ollama setup on resume. Phases already
        # ``completed`` are honored; phases newly ``pending`` will run
        # for the first time; phases that were ``skipped`` flip to
        # ``pending`` when the prerequisite is now present.
        if dpo_enabled and existing.status_of("dpo") == "skipped":
            existing.phases["dpo"].status = "pending"
        if export_enabled and existing.status_of("export") == "skipped":
            existing.phases["export"].status = "pending"
        return existing
    # Fresh run. If a state file is already there from a prior run with
    # the same output_dir, prefer to start fresh — the user explicitly
    # didn't pass --resume.
    fresh = RunState.new(
        run_id=run_id,
        output_dir=output_dir,
        args=_args_to_state_dict(args),
        dpo_enabled=dpo_enabled,
        export_enabled=export_enabled,
    )
    fresh.save()
    return fresh


def _args_to_state_dict(args: argparse.Namespace) -> dict[str, Any]:
    """Capture the subset of CLI args that ``athena train resume`` needs
    to re-invoke the run. Stored in the state file so the user doesn't
    have to remember every flag from the original invocation.
    """
    return {
        "base_model": args.base_model,
        "sft_dataset": args.sft_dataset,
        "dpo_dataset": args.dpo_dataset,
        "epochs": args.epochs,
        "lr": args.lr,
        "lora_rank": args.lora_rank,
        "output_name": args.output_name,
        "output_dir": args.output_dir,
    }


def _record_run_legacy(
    args: argparse.Namespace,
    output_name: str,
    output_dir: Path,
    sft_dataset: Path,
    dpo_dataset: Path | None,
    state: RunState,
) -> None:
    """Append a summary entry to the legacy ``~/.athena/training_state.json``
    history so ``athena train status`` keeps working. The per-run state
    file under ``output_dir`` is the source of truth for resumability;
    this is just the journal."""
    _record_run(
        args.base_model,
        output_name,
        output_dir,
        sft_dataset,
        dpo_dataset,
        sft=state.phases["sft"].exit_code,
        dpo=state.phases["dpo"].exit_code,
        export=state.phases["export"].exit_code,
        register=0 if state.status_of("export") == "completed" else None,
    )


def _cmd_resume(args: argparse.Namespace) -> int:
    """``athena train resume <output_name>`` — load the named run's state
    file, rehydrate the CLI args it was launched with, and continue
    from the first non-completed phase.
    """
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else (Path("transform") / "output" / args.output_name).resolve()
    )
    state = load_run_state(output_dir)
    if state is None:
        print(
            f"error: no state file at {output_dir}/.athena_train_state.json",
            file=sys.stderr,
        )
        return 2

    # Reconstruct an args-like object from the state file. Override with
    # any CLI flags the user explicitly passed to ``resume`` (e.g. they
    # added ``--dpo-dataset`` on the resume invocation).
    saved = dict(state.args)
    if args.base_model:
        saved["base_model"] = args.base_model
    if args.sft_dataset:
        saved["sft_dataset"] = args.sft_dataset
    if args.dpo_dataset is not None:
        saved["dpo_dataset"] = args.dpo_dataset

    if not saved.get("base_model") or not saved.get("sft_dataset"):
        print(
            "error: state file is missing base_model or sft_dataset; "
            "pass --base-model / --sft-dataset to rehydrate",
            file=sys.stderr,
        )
        return 2

    # argparse.Namespace stand-in.
    class _Args(argparse.Namespace):
        pass

    a = _Args()
    a.base_model = saved["base_model"]
    a.sft_dataset = saved["sft_dataset"]
    a.dpo_dataset = saved.get("dpo_dataset")
    a.epochs = saved.get("epochs", 3)
    a.lr = saved.get("lr", 2e-4)
    a.lora_rank = saved.get("lora_rank", 32)
    a.output_name = saved.get("output_name") or args.output_name
    a.output_dir = str(output_dir)
    a.resume = True

    print(f"resuming run: {state.run_id}")
    for line in state.summary_lines():
        print(line)
    print()
    return _cmd_run(a)


def _record_run(
    base_model: str,
    output_name: str,
    output_dir: Path,
    sft_dataset: Path,
    dpo_dataset: Path | None,
    *,
    sft: int | None,
    dpo: int | None,
    export: int | None,
    register: int | None,
) -> None:
    state = _load_state()
    state["runs"].append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "base_model": base_model,
            "output_name": output_name,
            "output_dir": str(output_dir),
            "sft_dataset": str(sft_dataset),
            "dpo_dataset": str(dpo_dataset) if dpo_dataset else None,
            "exit_codes": {
                "sft": sft,
                "dpo": dpo,
                "export": export,
                "register": register,
            },
        }
    )
    _save_state(state)


def _cmd_status(args: argparse.Namespace) -> int:  # noqa: ARG001
    state = _load_state()
    runs = state.get("runs", [])
    if not runs:
        print("(no training runs yet)")
        return 0
    last = runs[-1]
    print(f"last run: {last.get('timestamp')}")
    print(f"  base model:   {last.get('base_model')}")
    print(f"  output name:  {last.get('output_name')}")
    print(f"  output dir:   {last.get('output_dir')}")
    print(f"  SFT dataset:  {last.get('sft_dataset')}")
    if last.get("dpo_dataset"):
        print(f"  DPO dataset:  {last.get('dpo_dataset')}")
    exits = last.get("exit_codes") or {}
    print(
        f"  exit codes:   sft={exits.get('sft')}, dpo={exits.get('dpo')}, "
        f"export={exits.get('export')}, register={exits.get('register')}"
    )
    return 0


# ---- Parser ------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena train")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_review = sub.add_parser("review", help="Interactively label trajectories.")
    p_review.add_argument("--since-days", type=int, default=30)
    p_review.add_argument("--profile", default="default")
    p_review.add_argument(
        "--no-tui",
        action="store_true",
        help=(
            "Use the existing one-at-a-time prompt instead of the textual TUI "
            "(default: TUI). Falls back automatically if textual isn't installed."
        ),
    )
    p_review.add_argument(
        "--keymap",
        choices=["default", "vim", "basic"],
        default="default",
        help="TUI keymap; `basic` avoids Ctrl combos for terminals that swallow them.",
    )

    p_build = sub.add_parser("build-dataset", help="Build SFT + DPO JSONL.")
    p_build.add_argument("--since-days", type=int, default=30)
    p_build.add_argument("--include-auto-labels", action="store_true")
    p_build.add_argument(
        "--output-dir",
        default=str(Path("transform") / "datasets"),
    )
    p_build.add_argument("--chat-template", default="qwen-coder")
    p_build.add_argument("--profile", default="default")

    p_run = sub.add_parser("run", help="Run LoRA -> DPO -> GGUF -> ollama create.")
    p_run.add_argument("--base-model", required=True)
    p_run.add_argument("--sft-dataset", required=True)
    p_run.add_argument("--dpo-dataset", default=None)
    p_run.add_argument("--epochs", type=int, default=3)
    p_run.add_argument("--lr", type=float, default=2e-4)
    p_run.add_argument("--lora-rank", type=int, default=32)
    p_run.add_argument("--output-name", default=None)
    p_run.add_argument("--output-dir", default=None)
    p_run.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Continue from the state file at <output_dir>/.athena_train_state.json "
            "rather than starting fresh. Skips completed phases; retries "
            "failed/interrupted ones; for SFT, passes the latest HF "
            "checkpoint through so HF Trainer restores optimizer state."
        ),
    )

    p_resume = sub.add_parser(
        "resume",
        help=(
            "Resume a previous run by name (sugar for `run --resume "
            "--output-dir <inferred>`). Rehydrates CLI args from the state file."
        ),
    )
    p_resume.add_argument(
        "output_name", help="The run's output_name (e.g. 'qwen2.5-coder-14b-athena-1')."
    )
    p_resume.add_argument(
        "--output-dir",
        default=None,
        help="Explicit path; overrides the inferred 'transform/output/<output_name>' location.",
    )
    p_resume.add_argument(
        "--base-model", default=None, help="Override the base model recorded in the state file."
    )
    p_resume.add_argument(
        "--sft-dataset",
        default=None,
        help="Override the SFT dataset path recorded in the state file.",
    )
    p_resume.add_argument(
        "--dpo-dataset", default=None, help="Add or override a DPO dataset for this resume."
    )

    sub.add_parser("status", help="Show the last training run.")
    return ap


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "review":
        return _cmd_review(args)
    if args.cmd == "build-dataset":
        return _cmd_build_dataset(args)
    if args.cmd == "run":
        return _cmd_run(args)
    if args.cmd == "resume":
        return _cmd_resume(args)
    if args.cmd == "status":
        return _cmd_status(args)
    return 2
