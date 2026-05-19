"""Shell out to ``transform/scripts/`` to run training.

athena never re-implements training. It builds the dataset, then invokes
the scripts that ship in ``transform/``. The wrapper here is responsible
for resolving paths, choosing the right Python interpreter, and
translating between athena's terminology (``base_model``, ``learning_rate``,
``lora_rank``) and each script's actual CLI flag names.

The existing ``train_lora.py`` uses ``--base / --train / --out / --rank /
--alpha / --batch / --lr`` — we don't rewrite it. The DPO script we ship
in this phase mirrors that convention.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def _default_transform_dir() -> Path:
    """Return the bundled ``transform/`` directory inside the repo."""
    # athena/transform/runner.py → athena/transform → athena → repo root → transform
    return Path(__file__).resolve().parents[2] / "transform"


@dataclass
class TrainingRun:
    """Inputs for a single LoRA / DPO training run."""

    base_model: str
    sft_dataset: Path
    output_dir: Path
    dpo_dataset: Path | None = None
    epochs: int = 3
    learning_rate: float = 2e-4
    batch_size: int = 2
    grad_accum: int = 4
    seq_len: int = 4096
    lora_rank: int = 32
    lora_alpha: int = 32
    max_steps: int = -1
    extra_args: list[str] = field(default_factory=list)


def run_lora(
    run: TrainingRun,
    *,
    transform_dir: Path | None = None,
    python: str | None = None,
    runner: subprocess._SubprocessTarget | None = None,
) -> int:
    """Invoke ``transform/scripts/train_lora.py``. Returns the exit code.

    ``python`` defaults to ``sys.executable``. ``runner`` is a test seam —
    pass a callable with the ``subprocess.call`` signature to intercept.
    """
    transform_dir = transform_dir or _default_transform_dir()
    python = python or sys.executable
    cmd = [
        python,
        str(transform_dir / "scripts" / "train_lora.py"),
        "--base",
        run.base_model,
        "--train",
        str(run.sft_dataset),
        "--out",
        str(run.output_dir),
        "--epochs",
        str(run.epochs),
        "--lr",
        str(run.learning_rate),
        "--batch",
        str(run.batch_size),
        "--grad-accum",
        str(run.grad_accum),
        "--seq-len",
        str(run.seq_len),
        "--rank",
        str(run.lora_rank),
        "--alpha",
        str(run.lora_alpha),
        "--max-steps",
        str(run.max_steps),
        *run.extra_args,
    ]
    logger.info("running LoRA training: %s", " ".join(cmd))
    call = runner or subprocess.call
    return call(cmd, cwd=str(transform_dir))


def run_dpo(
    run: TrainingRun,
    sft_lora_path: Path,
    *,
    transform_dir: Path | None = None,
    python: str | None = None,
    runner: subprocess._SubprocessTarget | None = None,
) -> int:
    """Invoke ``transform/scripts/train_dpo.py`` on top of an SFT LoRA.

    Requires ``run.dpo_dataset`` to be set. Returns the exit code.
    """
    if run.dpo_dataset is None:
        raise ValueError("run_dpo requires TrainingRun.dpo_dataset to be set")
    transform_dir = transform_dir or _default_transform_dir()
    python = python or sys.executable
    cmd = [
        python,
        str(transform_dir / "scripts" / "train_dpo.py"),
        "--base",
        run.base_model,
        "--sft-lora",
        str(sft_lora_path),
        "--train",
        str(run.dpo_dataset),
        "--out",
        str(run.output_dir.with_name(run.output_dir.name + "-dpo")),
        "--epochs",
        str(max(1, run.epochs // 2)),  # DPO converges faster
        "--lr",
        str(run.learning_rate / 10),  # smaller LR for DPO
        "--batch",
        str(run.batch_size),
        "--seq-len",
        str(run.seq_len),
        *run.extra_args,
    ]
    logger.info("running DPO training: %s", " ".join(cmd))
    call = runner or subprocess.call
    return call(cmd, cwd=str(transform_dir))


def export_to_gguf(
    lora_path: Path,
    *,
    ollama_name: str,
    merged_out: Path | None = None,
    gguf_out: Path | None = None,
    quant: str = "q4_k_m",
    base_model: str | None = None,
    transform_dir: Path | None = None,
    python: str | None = None,
    runner: subprocess._SubprocessTarget | None = None,
) -> int:
    """Invoke ``transform/scripts/export_to_ollama.py`` to merge the
    LoRA, convert to GGUF, and register with Ollama under ``ollama_name``.
    """
    transform_dir = transform_dir or _default_transform_dir()
    python = python or sys.executable
    merged_out = merged_out or lora_path.parent / "merged"
    gguf_out = gguf_out or lora_path.parent / f"{ollama_name}.gguf"
    cmd = [
        python,
        str(transform_dir / "scripts" / "export_to_ollama.py"),
        "--adapter",
        str(lora_path),
        "--merged-out",
        str(merged_out),
        "--gguf-out",
        str(gguf_out),
        "--quant",
        quant,
        "--ollama-name",
        ollama_name,
    ]
    if base_model:
        cmd.extend(["--base", base_model])
    logger.info("exporting to Ollama: %s", " ".join(cmd))
    call = runner or subprocess.call
    return call(cmd, cwd=str(transform_dir))


def find_lora_adapter(output_dir: Path) -> Path | None:
    """Return the LoRA adapter dir inside ``output_dir``, or ``None``.

    train_lora.py writes the final adapter under ``<output_dir>/lora_out``
    by convention. If callers used a different layout, they pass the
    path through directly.
    """
    candidate = output_dir / "lora_out"
    if candidate.is_dir():
        return candidate
    if output_dir.is_dir() and (output_dir / "adapter_config.json").exists():
        return output_dir
    return None


def ensure_ollama_on_path() -> bool:
    """Return True iff the ``ollama`` binary is on PATH. Useful as a
    pre-flight check before the export step."""
    return shutil.which("ollama") is not None
