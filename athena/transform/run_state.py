"""Per-run state machine for ``athena train run``.

Each invocation of the closed training loop is split into three phases —
``sft``, ``dpo``, and ``export`` — each of which can independently
succeed, fail, or (for ``dpo``/``export``) be skipped when the user
didn't request it or a prerequisite is missing.

State is persisted to ``<output_dir>/.athena_train_state.json`` after
every transition. A failed or interrupted run can be picked up by
``athena train run --resume`` (or the sugar ``athena train resume
<output_name>``) which loads this file, skips ``completed`` phases,
and re-runs the rest. For ``sft`` specifically, the resume path also
detects the latest HF Trainer checkpoint under the run's checkpoint
directory and passes it through to ``train_lora.py`` so we don't burn
GPU-hours re-training from step zero.

The state file is JSON for one reason: a user staring at a half-failed
run at 3am should be able to ``cat`` it and immediately see what's
broken. That comes at the cost of atomicity — we use a
write-temp-then-rename pattern (same one as ``dataset.write_jsonl``)
to make crashed mid-writes harmless.

Backward compatibility: the legacy ``~/.athena/training_state.json``
append-only summary log written by ``_record_run`` in
``athena/cli/train.py`` is preserved. The new per-run state file
sits alongside it; ``athena train status`` still reads the legacy
log to show run history. They serve different purposes — the legacy
log is a journal of every run ever; this file is the resume cursor
for a single run.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

# Phase ordering is canonical — iteration order determines the pipeline
# topology. Add new phases by extending this tuple; the dataclass
# autopopulates entries for each name.
PHASES: tuple[str, ...] = ("sft", "dpo", "export")

PhaseStatus = Literal["pending", "running", "completed", "failed", "skipped"]


STATE_FILE_NAME = ".athena_train_state.json"

# Schema version stamped into the state file so future format changes
# can be detected and migrated rather than silently misinterpreted.
SCHEMA_VERSION = 1


@dataclass
class PhaseState:
    """Persistent record for a single phase of a training run.

    ``attempts`` increments every time the phase transitions from
    ``pending`` or ``failed`` back into ``running``; useful when a
    user resumes a flaky export several times and wants to know
    how many tries it took.
    """

    status: PhaseStatus = "pending"
    started_at: str | None = None
    completed_at: str | None = None
    exit_code: int | None = None
    error: str | None = None
    attempts: int = 0
    checkpoint: str | None = None  # path to latest HF checkpoint (sft only)


@dataclass
class RunState:
    """Persistent record for one ``athena train run`` invocation.

    ``args`` captures the original CLI arguments so ``athena train
    resume <output_name>`` can rehydrate the run without the user
    having to remember every flag. Stored as a plain dict (not the
    argparse Namespace) so the file stays JSON-roundtrippable.
    """

    run_id: str
    created_at: str
    output_dir: str
    args: dict[str, Any]
    phases: dict[str, PhaseState] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def new(
        cls,
        *,
        run_id: str,
        output_dir: Path,
        args: dict[str, Any],
        dpo_enabled: bool,
        export_enabled: bool,
    ) -> RunState:
        """Build a fresh state with all phases ``pending`` (or ``skipped``
        for phases the user opted out of).

        ``dpo_enabled`` is False when no ``--dpo-dataset`` was provided;
        ``export_enabled`` is False when ``ollama`` isn't on PATH at
        invocation time. Either can flip to ``pending`` later if a
        resume run re-runs with different inputs (we re-evaluate on
        every load).
        """
        phases: dict[str, PhaseState] = {}
        for name in PHASES:
            if name == "dpo" and not dpo_enabled:
                phases[name] = PhaseState(status="skipped")
            elif name == "export" and not export_enabled:
                phases[name] = PhaseState(status="skipped")
            else:
                phases[name] = PhaseState(status="pending")
        return cls(
            run_id=run_id,
            created_at=_now_iso(),
            output_dir=str(output_dir),
            args=dict(args),
            phases=phases,
        )

    # ---- Phase transitions ----

    def start_phase(self, name: str) -> None:
        ps = self._phase(name)
        ps.status = "running"
        ps.started_at = _now_iso()
        ps.attempts += 1
        ps.error = None  # clear stale error from a previous failed attempt

    def complete_phase(
        self,
        name: str,
        *,
        exit_code: int = 0,
        checkpoint: str | None = None,
    ) -> None:
        ps = self._phase(name)
        ps.status = "completed"
        ps.completed_at = _now_iso()
        ps.exit_code = exit_code
        if checkpoint is not None:
            ps.checkpoint = checkpoint

    def fail_phase(
        self,
        name: str,
        *,
        exit_code: int,
        error: str | None = None,
        checkpoint: str | None = None,
    ) -> None:
        """Mark a phase failed. ``checkpoint`` lets the SFT phase record
        where it got to so a later resume can pick up there even
        though the phase as a whole didn't complete."""
        ps = self._phase(name)
        ps.status = "failed"
        ps.completed_at = _now_iso()
        ps.exit_code = exit_code
        if error is not None:
            ps.error = error
        if checkpoint is not None:
            ps.checkpoint = checkpoint

    def skip_phase(self, name: str) -> None:
        ps = self._phase(name)
        ps.status = "skipped"
        ps.completed_at = _now_iso()

    # ---- Queries ----

    def status_of(self, name: str) -> PhaseStatus:
        return self._phase(name).status

    def needs_run(self, name: str) -> bool:
        """A phase needs running if it's ``pending``, ``running`` (the
        previous attempt was interrupted before recording a result),
        or ``failed`` (a resume should retry).
        """
        return self._phase(name).status in ("pending", "running", "failed")

    def next_runnable(self) -> str | None:
        """Return the first phase name (in canonical order) that needs
        running, or ``None`` if everything is ``completed`` or
        ``skipped``."""
        for name in PHASES:
            if self.needs_run(name):
                return name
        return None

    def is_complete(self) -> bool:
        return self.next_runnable() is None and any(
            self._phase(n).status == "completed" for n in PHASES
        )

    def invalidate_downstream(self, name: str) -> list[str]:
        """Reset any ``completed`` or ``failed`` phases that come **after**
        ``name`` in canonical order back to ``pending``. ``skipped``
        phases stay skipped — the user explicitly opted out.

        Use case: a resume that re-runs DPO successfully should also
        re-run export, because the export's input (the LoRA adapter)
        has changed. Without this, a resume that succeeds at DPO
        would leave the existing SFT-only GGUF in place.

        Returns the list of phase names that were reset, so the caller
        can log what's about to re-run.
        """
        if name not in PHASES:
            raise KeyError(f"unknown phase {name!r}; known: {PHASES}")
        idx = PHASES.index(name)
        reset: list[str] = []
        for downstream in PHASES[idx + 1 :]:
            ps = self._phase(downstream)
            if ps.status in ("completed", "failed"):
                ps.status = "pending"
                ps.started_at = None
                ps.completed_at = None
                ps.exit_code = None
                ps.error = None
                # Keep attempts cumulative; this is "additional work
                # caused by upstream change", not a fresh phase.
                reset.append(downstream)
        return reset

    def summary_lines(self) -> list[str]:
        """One-line-per-phase status summary, suitable for printing."""
        out = [f"run: {self.run_id}", f"output_dir: {self.output_dir}"]
        for name in PHASES:
            ps = self._phase(name)
            extra = []
            if ps.attempts:
                extra.append(f"attempts={ps.attempts}")
            if ps.exit_code is not None:
                extra.append(f"exit={ps.exit_code}")
            if ps.error:
                extra.append(f"error={ps.error!r}")
            if ps.checkpoint:
                extra.append(f"checkpoint={ps.checkpoint}")
            tail = f"  ({', '.join(extra)})" if extra else ""
            out.append(f"  {name:7s} {ps.status}{tail}")
        return out

    # ---- (De)serialization ----

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "output_dir": self.output_dir,
            "args": self.args,
            "phases": {name: asdict(ps) for name, ps in self.phases.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunState:
        version = data.get("schema_version", 0)
        if version > SCHEMA_VERSION:
            raise ValueError(
                f"state file schema_version={version} is newer than this "
                f"athena ({SCHEMA_VERSION}); upgrade athena or delete the file"
            )
        phases_raw = data.get("phases") or {}
        phases: dict[str, PhaseState] = {}
        for name in PHASES:
            entry = phases_raw.get(name) or {}
            phases[name] = PhaseState(
                status=entry.get("status", "pending"),
                started_at=entry.get("started_at"),
                completed_at=entry.get("completed_at"),
                exit_code=entry.get("exit_code"),
                error=entry.get("error"),
                attempts=int(entry.get("attempts", 0)),
                checkpoint=entry.get("checkpoint"),
            )
        return cls(
            run_id=data["run_id"],
            created_at=data.get("created_at", _now_iso()),
            output_dir=data.get("output_dir", ""),
            args=dict(data.get("args") or {}),
            phases=phases,
            schema_version=version or SCHEMA_VERSION,
        )

    def save(self, output_dir: Path | None = None) -> Path:
        """Atomically write the state file under ``output_dir`` (or the
        directory the state already names, when ``output_dir`` is ``None``).

        Same temp-and-rename pattern as :func:`dataset.write_jsonl` —
        a crash mid-write leaves the prior file (if any) untouched,
        never a half-written JSON file that would refuse to parse.
        """
        target_dir = Path(output_dir) if output_dir is not None else Path(self.output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / STATE_FILE_NAME
        tmp = path.with_name(path.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2, sort_keys=True)
                f.write("\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            tmp.replace(path)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return path

    # ---- Internals ----

    def _phase(self, name: str) -> PhaseState:
        if name not in self.phases:
            raise KeyError(f"unknown phase {name!r}; known: {tuple(self.phases)}")
        return self.phases[name]


def load(output_dir: Path) -> RunState | None:
    """Load the state file from ``output_dir``, or return ``None`` if it
    doesn't exist. Raises on corrupted JSON or schema version mismatch
    so the caller can refuse to proceed rather than silently start
    over and clobber a partially-completed run."""
    path = Path(output_dir) / STATE_FILE_NAME
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    return RunState.from_dict(data)


# ---- Checkpoint discovery ----------------------------------------------

# HF Trainer writes intermediate checkpoints under ``<save_dir>/checkpoint-N``
# where N is the global step count. We pick the one with the highest N
# as the resume point — the rest are older snapshots Trainer cycles
# through under ``save_total_limit``.
_CHECKPOINT_DIR_RE = re.compile(r"^checkpoint-(\d+)$")


def find_latest_checkpoint(checkpoint_dir: Path) -> Path | None:
    """Return the ``checkpoint-N`` subdir of ``checkpoint_dir`` with the
    highest N, or ``None`` if no checkpoint directories exist.

    A checkpoint dir is only considered valid if it contains a
    ``trainer_state.json`` (or at minimum some file — we use
    ``trainer_state.json`` because HF Trainer always writes it on
    every save and its presence reliably distinguishes a real
    checkpoint from a half-written one).
    """
    if not checkpoint_dir.is_dir():
        return None
    candidates: list[tuple[int, Path]] = []
    for entry in checkpoint_dir.iterdir():
        if not entry.is_dir():
            continue
        m = _CHECKPOINT_DIR_RE.match(entry.name)
        if not m:
            continue
        if not (entry / "trainer_state.json").exists():
            # Half-written or interrupted save; skip rather than risk
            # resuming from a corrupt state.
            continue
        candidates.append((int(m.group(1)), entry))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    return candidates[-1][1]


# ---- Helpers ----------------------------------------------------------


def _now_iso() -> str:
    """UTC-stamped ISO 8601 with seconds precision. Kept centralized so
    tests can monkeypatch a deterministic clock."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
