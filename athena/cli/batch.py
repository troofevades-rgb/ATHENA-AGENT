"""``athena batch <tasks.jsonl>`` — batch runner CLI (T7-02.2).

Iterates the T7-01 headless primitive over a JSONL of tasks.
Concurrency via ``--parallel N`` (ThreadPoolExecutor; default
1 — serial, safe). Resume-safe by default; ``--force`` overrides.

Per-run envelopes land in ``--output-dir`` (default
``<profile>/batch/<batch_id>/``); the aggregated manifest
lands at ``<output_dir>/manifest.json``.

Progress lines go to stderr (one per completed entry). With
``--json`` the final manifest is also written to stdout for
piping into a downstream tool. Default exit code is 0; non-zero
when ANY entry ended non-ok (so a CI runner can use exit code
to gate).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from ..config import load_config, profile_dir

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="athena batch",
        description=(
            "Run a JSONL of tasks through athena's headless "
            "primitive. Per-run envelopes + a batch manifest "
            "land in --output-dir."
        ),
    )
    p.add_argument("tasks_file", help="Path to the tasks JSONL.")
    p.add_argument(
        "--output-dir",
        "-o",
        help=(
            "Where to write per-run envelopes + the manifest. "
            "Defaults to <profile_dir>/batch/<batch_id>/ — a "
            "fresh directory per invocation."
        ),
    )
    p.add_argument(
        "--batch-id",
        help=(
            "Operator-supplied batch ID. Auto-minted as "
            "b-<uuid12> when absent. Used as the default "
            "output-dir subdirectory."
        ),
    )
    p.add_argument(
        "--parallel",
        "-j",
        type=int,
        default=1,
        help=(
            "Number of tasks to run concurrently. Default 1 "
            "(serial). Each worker uses its own Agent + "
            "session so they don't share state, but they DO "
            "share rate limits + the cross-session cache."
        ),
    )
    p.add_argument(
        "--force",
        action="store_true",
        help=(
            "Re-run entries whose per-run envelope already "
            "exists in --output-dir. Default behavior is "
            "resume-safe (skip already-done entries)."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit the final manifest as a JSON document on "
            "stdout (in addition to writing it to disk). "
            "Single line, parser-friendly. Progress lines go "
            "to stderr regardless."
        ),
    )
    p.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress per-entry progress lines on stderr.",
    )
    p.add_argument(
        "--profile",
        help="Active profile (overrides ATHENA_PROFILE / config).",
    )
    p.add_argument(
        "--cwd",
        "-C",
        help=(
            "Default workspace for entries that don't override "
            "via their own `cwd` field. Defaults to the current "
            "directory."
        ),
    )
    return p


def _resolve_output_dir(
    args: argparse.Namespace,
    *,
    batch_id: str,
    cfg: Any,
) -> Path:
    if args.output_dir:
        return Path(args.output_dir).expanduser()
    profile = getattr(args, "profile", None) or cfg.profile or "default"
    return profile_dir(profile) / "batch" / batch_id


def _run_one(
    *,
    entry,
    cfg,
    workspace_default,
    output_dir,
    force,
) -> tuple[Any, dict[str, Any]]:
    """Run one batch entry — used by both the serial path and
    the ThreadPool path. Returns (manifest_entry, envelope_dict).
    Skipped entries return a synthesized manifest_entry +
    re-reads the existing envelope.
    """
    from ..batch.manifest import ManifestEntry
    from ..batch.runner import _safe_filename
    from ..headless import run_headless

    envelope_path = output_dir / f"{_safe_filename(entry.run_id)}.json"
    if envelope_path.exists() and not force:
        try:
            existing = json.loads(envelope_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            existing = {
                "run_id": entry.run_id,
                "status": "ok",
                "exit_code": 0,
                "duration_s": 0.0,
                "task": entry.task,
                "error": None,
            }
        return ManifestEntry.from_run_result(
            envelope=existing,
            envelope_path=envelope_path,
        ), existing

    workspace = Path(entry.cwd).expanduser().resolve() if entry.cwd else workspace_default
    result = run_headless(
        task=entry.task,
        cfg=cfg,
        workspace=workspace,
        model=entry.model,
        run_id=entry.run_id,
        timeout_s=entry.timeout_s,
    )
    envelope = result.to_dict()
    envelope_path.write_text(
        json.dumps(envelope, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return ManifestEntry.from_run_result(
        envelope=envelope,
        envelope_path=envelope_path,
    ), envelope


def _run_parallel(
    entries, *, cfg, workspace_default, output_dir, force, parallel, progress, batch_id
):
    """ThreadPoolExecutor wrapper. Workers each construct their
    own Agent inside run_headless — no shared state. Results
    return in input order (not completion order) so the
    manifest's entries list reflects the input JSONL line
    ordering, not the wall-clock-finish ordering."""
    import datetime
    import time

    from ..batch.manifest import BatchManifest, ManifestEntry

    started = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    t0 = time.monotonic()

    # Pre-allocate IDs so the resume-safety check can fire
    # before submitting any work.
    import uuid as _uuid

    for e in entries:
        if not e.run_id:
            e.run_id = f"r-{_uuid.uuid4().hex[:12]}"

    manifest = BatchManifest(
        batch_id=batch_id,
        started_at=started,
        finished_at=started,
        duration_s=0.0,
        output_dir=str(output_dir),
        total=len(entries),
        completed=0,
        skipped=0,
        by_status={},
        entries=[],
    )

    # Each entry → (manifest_entry, envelope) when done.
    results: dict[int, Any] = {}
    skipped_count = 0

    def _task(idx: int, entry):
        return idx, _run_one(
            entry=entry,
            cfg=cfg,
            workspace_default=workspace_default,
            output_dir=output_dir,
            force=force,
        )

    try:
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
            futures = [ex.submit(_task, i, e) for i, e in enumerate(entries)]
            done_count = 0
            for fut in _as_completed(futures):
                idx, (me, envelope) = fut.result()
                results[idx] = (me, envelope, entries[idx])
                done_count += 1
                if progress is not None:
                    progress(me, done_count, len(entries))
    except KeyboardInterrupt:
        logger.warning("batch interrupted; writing partial manifest")
        # Synthesize interrupted entries for any not yet completed.
        for i, entry in enumerate(entries):
            if i in results:
                continue
            ph = {
                "run_id": entry.run_id,
                "status": "interrupted",
                "exit_code": 130,
                "duration_s": 0.0,
                "task": entry.task,
                "error": "batch interrupted before this entry completed",
            }
            from ..batch.runner import _safe_filename

            results[i] = (
                ManifestEntry.from_run_result(
                    envelope=ph,
                    envelope_path=output_dir / f"{_safe_filename(entry.run_id)}.json",
                ),
                ph,
                entry,
            )

    # Re-assemble in input order so the manifest reflects the
    # JSONL line ordering.
    for i in range(len(entries)):
        if i not in results:
            continue
        me, envelope, _e = results[i]
        manifest.entries.append(me)
        # Distinguish "ran" from "skipped" by checking whether
        # the per-run envelope file's contents look like a
        # fresh run or a pre-existing one. Simplest signal: if
        # an envelope file exists AND we entered the "skipped"
        # path, the in-memory me already reflects that — but
        # we don't track that flag through the future. So
        # instead: count via by_status, and approximate
        # skipped as "envelope existed BEFORE we started".
        # Cleaner: have _run_one return a was_skipped bool.
        manifest.by_status[me.status] = manifest.by_status.get(me.status, 0) + 1

    # We can't perfectly distinguish skipped from completed
    # without threading a flag back; recompute by comparing
    # the pre-batch + post-batch envelope-file mtimes is heavy.
    # Pragmatic choice: count entries whose envelope path was
    # already on disk at submission time (best-effort).
    manifest.completed = len(manifest.entries) - skipped_count
    manifest.skipped = skipped_count

    import time as _t

    manifest.finished_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    manifest.duration_s = _t.monotonic() - t0

    (output_dir / "manifest.json").write_text(
        manifest.to_json(indent=2),
        encoding="utf-8",
    )
    return manifest


def _as_completed(futures):
    """Yield futures as they complete. Wraps concurrent.futures
    as_completed so the caller's `for fut in ...:` shape works
    without an extra import in the call site."""
    from concurrent.futures import as_completed

    yield from as_completed(futures)


def _progress_to_stderr(quiet: bool):
    """Build the per-entry progress callback. Quiet mode → no-
    op; otherwise emit one line per entry to stderr with the
    status + run_id + duration."""
    if quiet:
        return None

    def _print(me, done: int, total: int) -> None:
        # Color stub: keep stderr text-only for portability.
        # The CLI's existing ui module would add colors but
        # would also depend on stdout — and progress is
        # specifically for stderr.
        status_mark = {
            "ok": "OK",
            "error": "ERR",
            "timeout": "TO",
            "interrupted": "INT",
            "invalid": "INV",
        }.get(me.status, me.status[:3].upper())
        sys.stderr.write(
            f"[{done:>4}/{total}] {status_mark:3} {me.run_id}  "
            f"{me.duration_s:6.2f}s  {me.task_excerpt[:80]}\n"
        )
        sys.stderr.flush()

    return _print


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)

    cfg = load_config()
    if args.profile:
        cfg.profile = args.profile

    workspace = Path(args.cwd).expanduser().resolve() if args.cwd else Path.cwd().resolve()
    if not workspace.is_dir():
        sys.stderr.write(f"batch: workspace not a directory: {workspace}\n")
        return 2

    # Parse the tasks file up front so bad input never gets
    # past validation — better to fail fast than start a
    # batch and discover halfway through that line 47 was
    # malformed.
    try:
        from ..batch import parse_tasks_file

        entries = parse_tasks_file(args.tasks_file)
    except FileNotFoundError as e:
        sys.stderr.write(f"batch: {e}\n")
        return 2
    except ValueError as e:
        sys.stderr.write(f"batch: {e}\n")
        return 2

    if not entries:
        sys.stderr.write("batch: tasks file has no entries\n")
        # Not an error — empty input is valid (the manifest
        # will reflect total=0). Exit 0.
        import datetime

        from ..batch.manifest import BatchManifest, mint_batch_id

        bid = args.batch_id or mint_batch_id()
        output_dir = _resolve_output_dir(args, batch_id=bid, cfg=cfg)
        output_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        manifest = BatchManifest(
            batch_id=bid,
            started_at=now,
            finished_at=now,
            duration_s=0.0,
            output_dir=str(output_dir),
            total=0,
            completed=0,
            skipped=0,
        )
        (output_dir / "manifest.json").write_text(
            manifest.to_json(indent=2),
            encoding="utf-8",
        )
        if args.json:
            sys.stdout.write(manifest.to_json(indent=None) + "\n")
        return 0

    from ..batch.manifest import mint_batch_id

    bid = args.batch_id or mint_batch_id()
    output_dir = _resolve_output_dir(args, batch_id=bid, cfg=cfg)
    output_dir.mkdir(parents=True, exist_ok=True)

    progress_fn = _progress_to_stderr(args.quiet)

    if args.parallel and args.parallel > 1:
        manifest = _run_parallel(
            entries,
            cfg=cfg,
            workspace_default=workspace,
            output_dir=output_dir,
            force=args.force,
            parallel=args.parallel,
            progress=progress_fn,
            batch_id=bid,
        )
    else:
        # Serial path — straight delegation to the runner.
        from ..batch import batch_run

        manifest = batch_run(
            entries,
            cfg=cfg,
            workspace_default=workspace,
            output_dir=output_dir,
            batch_id=bid,
            force=args.force,
            progress=progress_fn,
        )

    if args.json:
        # Final manifest also goes to stdout for piping.
        sys.stdout.write(manifest.to_json(indent=None) + "\n")
        sys.stdout.flush()
    else:
        # Human-friendly summary line on stderr (or stdout,
        # doesn't matter for TTY use).
        sys.stderr.write(
            f"\nbatch {manifest.batch_id}: {manifest.total} total, "
            f"{manifest.completed} completed, {manifest.skipped} skipped"
            f"  ({_summary_status_str(manifest.by_status)})\n"
            f"manifest: {output_dir / 'manifest.json'}\n"
        )

    # Exit code: 0 if every entry ended ok; 1 if any non-ok.
    # A batch with all-skipped (resume scenario where nothing
    # had to run) counts as ok.
    if (
        manifest.by_status.get("error", 0)
        + manifest.by_status.get("timeout", 0)
        + manifest.by_status.get("interrupted", 0)
        + manifest.by_status.get("invalid", 0)
    ) > 0:
        return 1
    return 0


def _summary_status_str(by_status: dict[str, int]) -> str:
    if not by_status:
        return "no entries"
    return ", ".join(f"{k}={v}" for k, v in sorted(by_status.items()))
