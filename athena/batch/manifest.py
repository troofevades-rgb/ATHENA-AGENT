"""Batch input + output data shapes (T7-02.1).

One entry per task on the input side; an aggregated manifest
on the output side. Both JSON-safe so the manifest round-trips
through ``json.dump`` cleanly + a downstream tool can parse
either with stdlib only.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any


# Max chars of task text we copy into the manifest summary so
# the file stays manageable for inspection. The full task lives
# in the per-run envelope on disk.
_TASK_EXCERPT_LIMIT = 240
_ERROR_EXCERPT_LIMIT = 200


@dataclasses.dataclass
class BatchEntry:
    """One task as it appears in the input JSONL.

    Required field: ``task``. Optional fields override the
    batch-level defaults (so a single tasks file can mix
    long-timeout / different-cwd / different-model runs).

    ``run_id`` is preserved verbatim when set; otherwise the
    runner mints one. Operator-supplied IDs let a batch
    re-run pick up where a previous run left off (the runner
    skips entries whose ``<output_dir>/<run_id>.json`` already
    exists unless ``--force``).
    """

    task: str
    run_id: str | None = None
    cwd: str | None = None
    timeout_s: float | None = None
    model: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BatchEntry":
        """Parse one JSONL line. Tolerates extra keys (forward-
        compat) by ignoring them. Raises ``ValueError`` when
        the required ``task`` field is missing or empty."""
        task = d.get("task")
        if not task or not str(task).strip():
            raise ValueError("BatchEntry requires non-empty 'task'")
        return cls(
            task=str(task),
            run_id=str(d["run_id"]) if d.get("run_id") else None,
            cwd=str(d["cwd"]) if d.get("cwd") else None,
            timeout_s=(
                float(d["timeout_s"]) if d.get("timeout_s") is not None else None
            ),
            model=str(d["model"]) if d.get("model") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"task": self.task}
        if self.run_id is not None:
            d["run_id"] = self.run_id
        if self.cwd is not None:
            d["cwd"] = self.cwd
        if self.timeout_s is not None:
            d["timeout_s"] = self.timeout_s
        if self.model is not None:
            d["model"] = self.model
        return d


@dataclasses.dataclass
class ManifestEntry:
    """One row in the aggregated manifest. Carries enough
    context for a glance-friendly summary without duplicating
    the per-run envelope (which lives at ``envelope_path``).
    """

    run_id: str
    status: str
    exit_code: int
    duration_s: float
    task_excerpt: str
    error_excerpt: str | None
    envelope_path: str

    @classmethod
    def from_run_result(
        cls,
        *,
        envelope: dict[str, Any],
        envelope_path: Path | str,
    ) -> "ManifestEntry":
        """Build a manifest row from a serialised RunResult dict
        plus the path the envelope was written to."""
        task = str(envelope.get("task", ""))
        err = envelope.get("error")
        return cls(
            run_id=str(envelope.get("run_id", "")),
            status=str(envelope.get("status", "")),
            exit_code=int(envelope.get("exit_code", 1)),
            duration_s=float(envelope.get("duration_s", 0.0)),
            task_excerpt=_excerpt(task, _TASK_EXCERPT_LIMIT),
            error_excerpt=_excerpt(err, _ERROR_EXCERPT_LIMIT) if err else None,
            envelope_path=str(envelope_path),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "run_id": self.run_id,
            "status": self.status,
            "exit_code": int(self.exit_code),
            "duration_s": round(float(self.duration_s), 3),
            "task_excerpt": self.task_excerpt,
            "envelope_path": self.envelope_path,
        }
        if self.error_excerpt is not None:
            d["error_excerpt"] = self.error_excerpt
        return d


@dataclasses.dataclass
class BatchManifest:
    """Aggregated outcome of one batch invocation.

    Written to ``<output_dir>/manifest.json`` at the end of the
    run (and at cancellation, with un-started entries marked
    ``status="not_started"``).
    """

    batch_id: str            # operator-supplied or auto-minted
    started_at: str          # ISO-8601 UTC
    finished_at: str
    duration_s: float
    output_dir: str
    total: int               # entries in the input
    completed: int           # status ∈ {ok, error, timeout, interrupted, invalid}
    skipped: int             # resume: already-done outputs
    by_status: dict[str, int] = dataclasses.field(default_factory=dict)
    entries: list[ManifestEntry] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round(float(self.duration_s), 3),
            "output_dir": self.output_dir,
            "total": int(self.total),
            "completed": int(self.completed),
            "skipped": int(self.skipped),
            "by_status": dict(self.by_status),
            "entries": [e.to_dict() for e in self.entries],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        """``indent=2`` is the default — manifests are for human
        inspection. Batch parsers that want a one-liner can
        pass ``indent=None``."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def mint_batch_id() -> str:
    """``b-<uuid12>`` — same shape family as ``r-<uuid12>``
    run IDs and ``t-<uuid12>`` task IDs so the prefix tells
    you the kind at a glance."""
    import uuid
    return f"b-{uuid.uuid4().hex[:12]}"


def _excerpt(s: str | None, limit: int) -> str:
    if s is None:
        return ""
    s = str(s).replace("\n", " ").replace("\r", " ").strip()
    if len(s) > limit:
        return s[: limit - 1] + "…"
    return s
