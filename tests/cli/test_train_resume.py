"""``athena train run --resume`` and ``athena train resume`` flow tests.

These exercise the orchestration in :func:`athena.cli.train._cmd_run`
that wraps each phase with state transitions, and the sugar command
that rehydrates a previous run's args from its state file.

All training-script subprocess calls are mocked — these tests verify
plumbing and state-file semantics, not training itself. Full E2E
training is a separate (GPU-required) test that lives outside CI.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

import athena.cli.train as train_cli
from athena.transform.run_state import STATE_FILE_NAME, load as load_run_state


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = train_cli.main(argv)
        except SystemExit as e:
            if isinstance(e.code, str):
                err.write(e.code + "\n")
                rc = 2
            else:
                rc = int(e.code or 0)
    return rc, out.getvalue(), err.getvalue()


@pytest.fixture
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    config_dir = home / ".athena"
    monkeypatch.setattr(train_cli, "TRAINING_STATE_PATH", config_dir / "training_state.json")
    monkeypatch.setattr("athena.config.CONFIG_DIR", config_dir)
    return home


def _write_sft(tmp_path: Path) -> Path:
    sft = tmp_path / "sft.jsonl"
    sft.write_text('{"messages": [{"role": "user", "content": "hi"}]}\n', encoding="utf-8")
    return sft


def _write_dpo(tmp_path: Path) -> Path:
    dpo = tmp_path / "dpo.jsonl"
    dpo.write_text(
        '{"prompt": "p", "chosen": "c", "rejected": "r"}\n', encoding="utf-8"
    )
    return dpo


def _stub_phases(monkeypatch, *, sft_rc=0, dpo_rc=0, export_rc=0, create_adapter=True):
    """Install fakes for the three subprocess phases. Returns a list
    that records the call order so tests can assert on it."""
    calls: list[str] = []

    def fake_lora(run, **kwargs):
        calls.append("lora")
        if create_adapter and sft_rc == 0:
            adapter = Path(run.output_dir) / "lora_out"
            adapter.mkdir(parents=True, exist_ok=True)
        return sft_rc

    def fake_dpo(run, sft_lora, **kwargs):
        calls.append("dpo")
        return dpo_rc

    def fake_export(lora_path, *, ollama_name, **kwargs):
        calls.append("export")
        return export_rc

    monkeypatch.setattr(train_cli, "run_lora", fake_lora)
    monkeypatch.setattr(train_cli, "run_dpo", fake_dpo)
    monkeypatch.setattr(train_cli, "export_to_gguf", fake_export)
    monkeypatch.setattr(train_cli, "ensure_ollama_on_path", lambda: True)
    return calls


# ---- State file is written on every run ---------------------------------


def test_run_writes_state_file_after_each_phase(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    sft = _write_sft(tmp_path)
    dpo = _write_dpo(tmp_path)
    out_dir = tmp_path / "run-out"
    _stub_phases(monkeypatch)

    rc, _, _ = _run(
        ["run", "--base-model", "qwen2.5:14b", "--sft-dataset", str(sft),
         "--dpo-dataset", str(dpo), "--output-dir", str(out_dir)],
    )
    assert rc == 0
    state_file = out_dir / STATE_FILE_NAME
    assert state_file.exists()
    state = load_run_state(out_dir)
    assert state is not None
    assert state.status_of("sft") == "completed"
    assert state.status_of("dpo") == "completed"
    assert state.status_of("export") == "completed"


def test_run_state_records_args_for_resume(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """The state file must capture enough args that ``athena train resume``
    can rehydrate a fresh invocation without the user re-typing flags."""
    sft = _write_sft(tmp_path)
    out_dir = tmp_path / "run-out"
    _stub_phases(monkeypatch)
    _run(
        ["run", "--base-model", "qwen2.5:14b", "--sft-dataset", str(sft),
         "--epochs", "5", "--lr", "1e-4", "--output-dir", str(out_dir)],
    )
    state = load_run_state(out_dir)
    assert state is not None
    assert state.args["base_model"] == "qwen2.5:14b"
    assert state.args["sft_dataset"] == str(sft)
    assert state.args["epochs"] == 5
    assert state.args["lr"] == 1e-4


def test_run_state_marks_skipped_when_no_dpo(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    sft = _write_sft(tmp_path)
    out_dir = tmp_path / "run-out"
    _stub_phases(monkeypatch)
    _run(
        ["run", "--base-model", "x", "--sft-dataset", str(sft), "--output-dir", str(out_dir)],
    )
    state = load_run_state(out_dir)
    assert state is not None
    assert state.status_of("dpo") == "skipped"


def test_run_state_marks_skipped_when_no_ollama(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """If ollama isn't on PATH, export phase must be skipped, not failed."""
    sft = _write_sft(tmp_path)
    out_dir = tmp_path / "run-out"
    calls = _stub_phases(monkeypatch)
    monkeypatch.setattr(train_cli, "ensure_ollama_on_path", lambda: False)
    rc, _, _ = _run(
        ["run", "--base-model", "x", "--sft-dataset", str(sft), "--output-dir", str(out_dir)],
    )
    assert rc == 0
    assert "export" not in calls
    state = load_run_state(out_dir)
    assert state is not None
    assert state.status_of("export") == "skipped"


# ---- Failure paths -----------------------------------------------------


def test_run_sft_failure_marks_state_failed(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    sft = _write_sft(tmp_path)
    out_dir = tmp_path / "run-out"
    _stub_phases(monkeypatch, sft_rc=17, create_adapter=False)
    rc, _, _ = _run(
        ["run", "--base-model", "x", "--sft-dataset", str(sft), "--output-dir", str(out_dir)],
    )
    assert rc == 17
    state = load_run_state(out_dir)
    assert state is not None
    assert state.status_of("sft") == "failed"
    assert state.phases["sft"].exit_code == 17
    # Downstream phases were never touched.
    assert state.status_of("dpo") in ("pending", "skipped")
    assert state.status_of("export") in ("pending", "skipped")


def test_run_dpo_failure_is_soft_continues_to_export(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """DPO failure has always been a warning — run continues with the
    SFT-only adapter. The state file records the failure for the
    next resume to retry."""
    sft = _write_sft(tmp_path)
    dpo = _write_dpo(tmp_path)
    out_dir = tmp_path / "run-out"
    calls = _stub_phases(monkeypatch, dpo_rc=1)
    rc, _, err = _run(
        ["run", "--base-model", "x", "--sft-dataset", str(sft),
         "--dpo-dataset", str(dpo), "--output-dir", str(out_dir)],
    )
    assert rc == 0
    assert calls == ["lora", "dpo", "export"]
    assert "DPO training failed" in err
    state = load_run_state(out_dir)
    assert state is not None
    assert state.status_of("sft") == "completed"
    assert state.status_of("dpo") == "failed"
    assert state.status_of("export") == "completed"


def test_run_export_failure_marks_state(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    sft = _write_sft(tmp_path)
    out_dir = tmp_path / "run-out"
    _stub_phases(monkeypatch, export_rc=5)
    rc, _, _ = _run(
        ["run", "--base-model", "x", "--sft-dataset", str(sft), "--output-dir", str(out_dir)],
    )
    assert rc == 5
    state = load_run_state(out_dir)
    assert state is not None
    assert state.status_of("sft") == "completed"
    assert state.status_of("export") == "failed"


# ---- Resume flow -------------------------------------------------------


def test_resume_skips_completed_phases(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """First run: SFT succeeds, export fails. Resume: only export
    re-runs; SFT is NOT invoked again."""
    sft = _write_sft(tmp_path)
    out_dir = tmp_path / "run-out"

    # First invocation: export fails.
    calls = _stub_phases(monkeypatch, export_rc=1)
    rc, _, _ = _run(
        ["run", "--base-model", "x", "--sft-dataset", str(sft), "--output-dir", str(out_dir)],
    )
    assert rc == 1
    assert calls == ["lora", "export"]

    # Second invocation: --resume; only export should re-run.
    calls = _stub_phases(monkeypatch)  # all succeed now (fresh calls list)
    rc, _, _ = _run(
        ["run", "--base-model", "x", "--sft-dataset", str(sft),
         "--output-dir", str(out_dir), "--resume"],
    )
    assert rc == 0
    assert calls == ["export"]
    state = load_run_state(out_dir)
    assert state is not None
    assert state.is_complete()


def test_resume_passes_checkpoint_to_sft(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """If a prior SFT attempt left a checkpoint-N dir on disk, the
    resume invocation must pass that path through to ``run_lora`` so
    HF Trainer restores optimizer state rather than starting from
    step zero. We capture the resume_from_checkpoint attr on the
    TrainingRun the fake observes.
    """
    sft = _write_sft(tmp_path)
    out_dir = tmp_path / "run-out"

    # First invocation: SFT fails. Manually drop a checkpoint dir
    # to simulate HF Trainer having saved one before the crash.
    ckpt_root = out_dir / "checkpoints"
    ckpt_root.mkdir(parents=True)
    ckpt_dir = ckpt_root / "checkpoint-200"
    ckpt_dir.mkdir()
    (ckpt_dir / "trainer_state.json").write_text("{}", encoding="utf-8")

    _stub_phases(monkeypatch, sft_rc=1, create_adapter=False)
    _run(["run", "--base-model", "x", "--sft-dataset", str(sft),
          "--output-dir", str(out_dir)])

    # Second invocation: capture the resume_from_checkpoint passed in.
    observed: dict = {}

    def capture_lora(run, **kwargs):
        observed["resume_from_checkpoint"] = run.resume_from_checkpoint
        observed["checkpoint_dir"] = run.checkpoint_dir
        (Path(run.output_dir) / "lora_out").mkdir(parents=True, exist_ok=True)
        return 0

    monkeypatch.setattr(train_cli, "run_lora", capture_lora)
    monkeypatch.setattr(train_cli, "run_dpo", lambda *a, **k: 0)
    monkeypatch.setattr(train_cli, "export_to_gguf", lambda *a, **k: 0)
    monkeypatch.setattr(train_cli, "ensure_ollama_on_path", lambda: True)

    rc, _, _ = _run(
        ["run", "--base-model", "x", "--sft-dataset", str(sft),
         "--output-dir", str(out_dir), "--resume"],
    )
    assert rc == 0
    assert observed["resume_from_checkpoint"] is not None
    assert observed["resume_from_checkpoint"].name == "checkpoint-200"


def test_resume_invalidates_downstream_on_late_dpo_success(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """First run: SFT ok, DPO fails (soft), export completes on SFT-only.
    Resume: DPO succeeds → export must re-run on the new DPO adapter."""
    sft = _write_sft(tmp_path)
    dpo = _write_dpo(tmp_path)
    out_dir = tmp_path / "run-out"

    # First run: DPO fails, export succeeds.
    _stub_phases(monkeypatch, dpo_rc=1)
    _run(
        ["run", "--base-model", "x", "--sft-dataset", str(sft),
         "--dpo-dataset", str(dpo), "--output-dir", str(out_dir)],
    )
    state = load_run_state(out_dir)
    assert state is not None
    assert state.status_of("dpo") == "failed"
    assert state.status_of("export") == "completed"

    # Resume: all succeed now.
    calls = _stub_phases(monkeypatch)
    rc, stdout, _ = _run(
        ["run", "--base-model", "x", "--sft-dataset", str(sft),
         "--dpo-dataset", str(dpo), "--output-dir", str(out_dir), "--resume"],
    )
    assert rc == 0
    # DPO retried; export re-ran because DPO succeeded.
    assert calls == ["dpo", "export"]
    assert "due to upstream change" in stdout


def test_resume_already_complete_is_noop(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    sft = _write_sft(tmp_path)
    out_dir = tmp_path / "run-out"
    _stub_phases(monkeypatch)
    _run(["run", "--base-model", "x", "--sft-dataset", str(sft),
          "--output-dir", str(out_dir)])

    calls = _stub_phases(monkeypatch)
    rc, stdout, _ = _run(
        ["run", "--base-model", "x", "--sft-dataset", str(sft),
         "--output-dir", str(out_dir), "--resume"],
    )
    assert rc == 0
    assert calls == []  # nothing re-ran
    assert "already complete" in stdout


def test_resume_without_state_file_errors(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    sft = _write_sft(tmp_path)
    out_dir = tmp_path / "no-such-run"
    _stub_phases(monkeypatch)
    rc, _, err = _run(
        ["run", "--base-model", "x", "--sft-dataset", str(sft),
         "--output-dir", str(out_dir), "--resume"],
    )
    assert rc == 2
    assert "no state file" in err


# ---- `athena train resume <output_name>` sugar -------------------------


def test_resume_sugar_command_rehydrates_args(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """``athena train resume <output_name>`` should pick up base_model
    and sft_dataset from the state file — the user doesn't repeat them."""
    sft = _write_sft(tmp_path)
    out_dir = tmp_path / "the-run"
    _stub_phases(monkeypatch, export_rc=1)
    _run(["run", "--base-model", "qwen2.5:14b", "--sft-dataset", str(sft),
          "--output-dir", str(out_dir)])

    calls = _stub_phases(monkeypatch)
    # Note: no --base-model, no --sft-dataset on the resume invocation.
    rc, stdout, _ = _run(["resume", "the-run", "--output-dir", str(out_dir)])
    assert rc == 0
    assert calls == ["export"]
    assert "resuming run" in stdout


def test_resume_sugar_command_can_override_args(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """The user can supply an override (e.g. add a DPO dataset post-hoc)."""
    sft = _write_sft(tmp_path)
    out_dir = tmp_path / "the-run"
    _stub_phases(monkeypatch)  # first run completes with no DPO
    _run(["run", "--base-model", "x", "--sft-dataset", str(sft),
          "--output-dir", str(out_dir)])
    state = load_run_state(out_dir)
    assert state is not None
    assert state.status_of("dpo") == "skipped"
    assert state.is_complete()  # already done

    # Add a DPO dataset and resume — should flip dpo from skipped to
    # pending and re-run export downstream of it.
    dpo = _write_dpo(tmp_path)
    calls = _stub_phases(monkeypatch)
    rc, _, _ = _run(
        ["resume", "the-run", "--output-dir", str(out_dir),
         "--dpo-dataset", str(dpo)],
    )
    assert rc == 0
    assert "dpo" in calls
    state = load_run_state(out_dir)
    assert state is not None
    assert state.status_of("dpo") == "completed"


def test_resume_sugar_missing_state_errors(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    out_dir = tmp_path / "missing-run"
    rc, _, err = _run(["resume", "missing-run", "--output-dir", str(out_dir)])
    assert rc == 2
    assert "no state file" in err
