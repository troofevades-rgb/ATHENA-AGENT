"""Batch runner core (T7-02.1).

Reads a JSONL tasks file; iterates :func:`athena.headless.run_headless`
per entry; writes each run's envelope to disk; aggregates a
manifest. Resume-safe by default — entries whose envelope file
already exists are skipped (``force=True`` overrides).

Serial execution in this module; the T7-02.2 CLI layer adds the
``--parallel`` ThreadPoolExecutor wrapper around it.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from ..config import Config
from .manifest import (
    BatchEntry,
    BatchManifest,
    ManifestEntry,
    mint_batch_id,
)

logger = logging.getLogger(__name__)


# A ProgressFn is called once after each run with the manifest
# entry for the just-finished (or just-skipped) task. The CLI
# layer uses this to write per-run status lines to stderr.
ProgressFn = Callable[[ManifestEntry, int, int], None]


# RunFn — what we call per task. Injectable so tests stub
# run_headless without booting a real Agent. Same shape as
# the real ``run_headless`` for everything that matters
# (returns something with .status / .exit_code / .to_dict()).
# Production calls athena.headless.runner.run_headless directly;
# tests inject a callable that returns a RunResult-shape object.
RunFn = Callable[..., Any]


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def parse_tasks_file(path: Path | str) -> list[BatchEntry]:
    """Read a JSONL tasks file. One object per line. Blank lines
    + lines starting with ``#`` are ignored (comment shebang at
    the top is fine).

    Raises ``ValueError`` with a line number when a line isn't
    valid JSON or doesn't carry a non-empty ``task`` — the CLI
    surfaces this as ``exit 2``, the operator fixes their input.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"tasks file not found: {p}")
    out: list[BatchEntry] = []
    for line_no, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"tasks file line {line_no}: not valid JSON: {e}"
            ) from None
        if not isinstance(obj, dict):
            raise ValueError(
                f"tasks file line {line_no}: expected an object, got {type(obj).__name__}"
            )
        try:
            out.append(BatchEntry.from_dict(obj))
        except ValueError as e:
            raise ValueError(f"tasks file line {line_no}: {e}") from None
    return out


def _safe_filename(run_id: str) -> str:
    """Filename-safe form of the run_id. The auto-minted format
    (``r-<uuid12>``) is already safe; operator-supplied IDs
    might have slashes / spaces / non-ASCII. Replace anything
    not in ``[A-Za-z0-9._-]`` with ``_`` so paths stay sane on
    every OS."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", run_id)
    return safe.strip("._") or run_id  # never return empty


def batch_run(
    entries: Iterable[BatchEntry],
    *,
    cfg: Config,
    workspace_default: Path,
    output_dir: Path,
    batch_id: str | None = None,
    force: bool = False,
    progress: ProgressFn | None = None,
    run_fn: RunFn | None = None,
) -> BatchManifest:
    """Execute a batch serially. Returns the aggregated manifest.

    Arguments:
      ``entries`` — iterable of :class:`BatchEntry`. The caller
        already validated them (via :func:`parse_tasks_file`).
      ``cfg`` — loaded :class:`Config`.
      ``workspace_default`` — workspace path used when an entry
        doesn't override via ``entry.cwd``.
      ``output_dir`` — per-run envelopes + manifest land here.
        Created if missing.
      ``batch_id`` — operator-supplied or auto-minted
        ``b-<uuid12>``. Echoed into the manifest.
      ``force`` — re-run entries whose envelope already exists.
        Default False (resume-safe).
      ``progress`` — callback fired once per entry with
        ``(manifest_entry, done, total)``. The CLI passes a
        stderr writer.
      ``run_fn`` — test seam. Defaults to
        ``athena.headless.run_headless``.

    Manifest is written to ``output_dir/manifest.json`` at the
    end + at each interruption (so a Ctrl+C still leaves a
    partial manifest on disk).
    """
    entries_list = list(entries)
    bid = batch_id or mint_batch_id()
    started = _now_iso()
    t0 = time.monotonic()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if run_fn is None:
        from ..headless import run_headless as _run_headless
        run_fn = _run_headless

    # Pre-allocate run_ids so the manifest's entries list has a
    # stable shape even if a worker raises mid-run. Each entry ID
    # has the same shape family as the ones run_headless mints
    # internally, but is minted here so resume-safety can key off
    # it before the run even starts.
    import uuid
    for i, entry in enumerate(entries_list):
        if not entry.run_id:
            entry.run_id = f"r-{uuid.uuid4().hex[:12]}"
            entries_list[i] = entry  # dataclass is mutable

    manifest = BatchManifest(
        batch_id=bid,
        started_at=started,
        finished_at=started,  # rewritten at end
        duration_s=0.0,
        output_dir=str(output_dir),
        total=len(entries_list),
        completed=0,
        skipped=0,
        by_status={},
        entries=[],
    )

    total = len(entries_list)
    try:
        for idx, entry in enumerate(entries_list, start=1):
            envelope_path = output_dir / f"{_safe_filename(entry.run_id)}.json"

            # Resume-safety: skip when the envelope already exists.
            if envelope_path.exists() and not force:
                logger.info(
                    "batch %s: skipping %s (already done)",
                    bid, entry.run_id,
                )
                try:
                    existing = json.loads(
                        envelope_path.read_text(encoding="utf-8")
                    )
                except Exception:  # noqa: BLE001
                    existing = {"run_id": entry.run_id, "status": "ok",
                                "exit_code": 0, "duration_s": 0.0,
                                "task": entry.task, "error": None}
                me = ManifestEntry.from_run_result(
                    envelope=existing, envelope_path=envelope_path,
                )
                manifest.entries.append(me)
                manifest.skipped += 1
                manifest.by_status[me.status] = manifest.by_status.get(me.status, 0) + 1
                if progress is not None:
                    progress(me, idx, total)
                continue

            workspace = (
                Path(entry.cwd).expanduser().resolve()
                if entry.cwd else workspace_default
            )

            result = run_fn(
                task=entry.task,
                cfg=cfg,
                workspace=workspace,
                model=entry.model,
                run_id=entry.run_id,
                timeout_s=entry.timeout_s,
            )

            envelope = result.to_dict() if hasattr(result, "to_dict") else dict(result)
            envelope_path.write_text(
                json.dumps(envelope, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            me = ManifestEntry.from_run_result(
                envelope=envelope, envelope_path=envelope_path,
            )
            manifest.entries.append(me)
            manifest.completed += 1
            manifest.by_status[me.status] = manifest.by_status.get(me.status, 0) + 1
            if progress is not None:
                progress(me, idx, total)

    except KeyboardInterrupt:
        # Partial manifest with un-started entries marked.
        logger.warning("batch %s: interrupted", bid)
        seen_ids = {e.run_id for e in manifest.entries}
        for entry in entries_list:
            if entry.run_id in seen_ids:
                continue
            placeholder_envelope = {
                "run_id": entry.run_id,
                "status": "interrupted",
                "exit_code": 130,
                "duration_s": 0.0,
                "task": entry.task,
                "error": "batch interrupted before this entry ran",
            }
            ph_path = output_dir / f"{_safe_filename(entry.run_id)}.json"
            me = ManifestEntry.from_run_result(
                envelope=placeholder_envelope, envelope_path=ph_path,
            )
            manifest.entries.append(me)
            manifest.by_status["interrupted"] = manifest.by_status.get("interrupted", 0) + 1
    finally:
        manifest.finished_at = _now_iso()
        manifest.duration_s = time.monotonic() - t0
        (output_dir / "manifest.json").write_text(
            manifest.to_json(indent=2), encoding="utf-8",
        )

    return manifest
