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
from datetime import datetime, timezone
from pathlib import Path

from ..config import CONFIG_DIR
from ..config import profile_dir as _profile_dir
from ..sessions.store import SessionStore
from ..transform.classifier import auto_classify, extract_trajectories
from ..transform.dataset import (
    build_dpo_dataset,
    build_sft_dataset,
    write_jsonl,
)
from ..transform.review import ReviewSession, default_prompt, load_labels
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


def _load_state() -> dict:
    if not TRAINING_STATE_PATH.exists():
        return {"runs": []}
    try:
        data = json.loads(TRAINING_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"runs": []}
    if not isinstance(data, dict) or "runs" not in data:
        return {"runs": []}
    return data


def _save_state(state: dict) -> None:
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


def _cmd_review(args) -> int:
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


def _cmd_review_classic(profile_dir: Path, args) -> int:
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


def _enumerate_trajectories(profile_dir: Path, since_days: int, include_auto_labels: bool):
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


def _cmd_build_dataset(args) -> int:
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
    # DPO pair extraction: trajectories labeled preference_pair, paired with
    # the immediately-preceding "bad" trajectory in the same session.
    pairs = _build_preference_pairs(trajectories)
    dpo = build_dpo_dataset(pairs, chat_template=args.chat_template)

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
    else:
        print("(no preference pairs found - DPO file not written)", file=sys.stderr)

    return 0 if sft or dpo else 1


def _build_preference_pairs(trajectories):
    """Pair each preference_pair trajectory with the prior bad one in its
    session. Returns a list of (chosen, rejected) tuples — chosen is the
    recovery (preference_pair), rejected is the original bad attempt."""
    out: list[tuple] = []
    by_session: dict[str, list] = {}
    for t in trajectories:
        by_session.setdefault(t.session_id, []).append(t)
    for sid, sess in by_session.items():
        for i, t in enumerate(sess):
            if t.user_label != "preference_pair":
                continue
            # Find the nearest prior bad trajectory.
            for j in range(i - 1, -1, -1):
                if sess[j].user_label == "bad":
                    out.append((t, sess[j]))
                    break
    return out


def _cmd_run(args) -> int:
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
        else Path("transform") / "output" / output_name
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    run = TrainingRun(
        base_model=args.base_model,
        sft_dataset=sft_dataset,
        dpo_dataset=dpo_dataset,
        output_dir=output_dir,
        epochs=args.epochs,
        learning_rate=args.lr,
        lora_rank=args.lora_rank,
    )

    print(f"=== Phase 1: LoRA SFT -> {output_dir}")
    rc_sft = run_lora(run)
    if rc_sft != 0:
        print(f"error: LoRA training failed (exit {rc_sft})", file=sys.stderr)
        _record_run(
            args.base_model,
            output_name,
            output_dir,
            sft_dataset,
            None,
            sft=rc_sft,
            dpo=None,
            export=None,
            register=None,
        )
        return rc_sft

    sft_lora = find_lora_adapter(output_dir)
    if sft_lora is None:
        print(f"error: could not locate SFT LoRA adapter under {output_dir}", file=sys.stderr)
        return 1

    rc_dpo: int | None = None
    final_lora = sft_lora
    if dpo_dataset is not None:
        print("=== Phase 2: DPO on top of SFT LoRA")
        rc_dpo = run_dpo(run, sft_lora)
        if rc_dpo != 0:
            print(
                f"warning: DPO training failed (exit {rc_dpo}); proceeding with SFT-only adapter",
                file=sys.stderr,
            )
        else:
            dpo_out = output_dir.with_name(output_dir.name + "-dpo")
            maybe_dpo_lora = find_lora_adapter(dpo_out)
            if maybe_dpo_lora is not None:
                final_lora = maybe_dpo_lora

    if not ensure_ollama_on_path():
        print(
            "warning: 'ollama' not on PATH — skipping GGUF export and "
            "registration. Run export_to_ollama.py manually.",
            file=sys.stderr,
        )
        _record_run(
            args.base_model,
            output_name,
            output_dir,
            sft_dataset,
            dpo_dataset,
            sft=rc_sft,
            dpo=rc_dpo,
            export=None,
            register=None,
        )
        return 0

    print(f"=== Phase 3: GGUF export + ollama create {output_name}")
    rc_export = export_to_gguf(
        final_lora,
        ollama_name=output_name,
        base_model=args.base_model,
    )
    if rc_export != 0:
        print(f"error: GGUF export failed (exit {rc_export})", file=sys.stderr)
        _record_run(
            args.base_model,
            output_name,
            output_dir,
            sft_dataset,
            dpo_dataset,
            sft=rc_sft,
            dpo=rc_dpo,
            export=rc_export,
            register=None,
        )
        return rc_export

    _record_run(
        args.base_model,
        output_name,
        output_dir,
        sft_dataset,
        dpo_dataset,
        sft=rc_sft,
        dpo=rc_dpo,
        export=rc_export,
        register=0,
    )
    print(f"\n[ok] training complete. New Ollama model: {output_name}")
    print(f"  athena model switch {output_name}   # to make it the default")
    return 0


def _record_run(
    base_model, output_name, output_dir, sft_dataset, dpo_dataset, *, sft, dpo, export, register
):
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


def _cmd_status(args) -> int:  # noqa: ARG001
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
    if args.cmd == "status":
        return _cmd_status(args)
    return 2
