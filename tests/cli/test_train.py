"""athena train CLI."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

import athena.cli.train as train_cli
from athena.sessions.store import SessionMeta, SessionStore
from athena.transform.review import save_label


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
    # Also redirect CONFIG_DIR / profile_dir if anything reads them.
    monkeypatch.setattr("athena.config.CONFIG_DIR", config_dir)
    return home


# ---- review subcommand -------------------------------------------------


def test_train_review_subcommand(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """athena train review walks pending trajectories using the default prompt;
    we replace the prompt with a script and verify the labels persist."""
    # Build a session under the isolated home so the CLI's _profile_dir
    # resolves to it.
    profile = isolated_home / ".athena" / "profiles" / "default"
    store = SessionStore(profile)
    meta = SessionMeta(
        session_id="s1",
        profile="default",
        model="qwen2.5-coder:14b",
        workspace=str(tmp_path),
    )
    store.open_session(meta)
    for m in [
        {"role": "user", "content": "do work"},
        {"role": "assistant", "content": "done"},
    ]:
        store.append_turn("s1", m)
    store.close_session("s1")
    store.close()

    # Replace the default prompt with a scripted one that labels everything good.
    monkeypatch.setattr(
        train_cli,
        "default_prompt",
        lambda t, suggestion: "good",
    )
    rc, stdout, _ = _run(["review", "--since-days", "365"])
    assert rc == 0
    assert "labeled" in stdout
    # Label persisted to disk:
    label_path = profile / "labels" / "s1.json"
    assert label_path.exists()
    data = json.loads(label_path.read_text(encoding="utf-8"))
    assert data == {"0-1": "good"}


# ---- build-dataset subcommand ------------------------------------------


def test_train_build_dataset_subcommand(isolated_home: Path, tmp_path: Path):
    """build-dataset walks user-labeled sessions and writes SFT JSONL."""
    profile = isolated_home / ".athena" / "profiles" / "default"
    store = SessionStore(profile)
    meta = SessionMeta(
        session_id="s1",
        profile="default",
        model="qwen2.5-coder:14b",
    )
    store.open_session(meta)
    for m in [
        {"role": "user", "content": "do work"},
        {"role": "assistant", "content": "done"},
    ]:
        store.append_turn("s1", m)
    store.close_session("s1")
    store.close()
    # User-label it as good.
    save_label(profile, "s1", "0-1", "good")

    out_dir = tmp_path / "datasets"
    rc, stdout, _ = _run(
        [
            "build-dataset",
            "--since-days",
            "365",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0
    written = list(out_dir.glob("sft-*.jsonl"))
    assert len(written) == 1
    line = written[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(line) == 1
    parsed = json.loads(line[0])
    assert parsed["messages"][0]["content"] == "do work"


def test_train_build_dataset_no_labels_exits_nonzero(isolated_home: Path, tmp_path: Path):
    out_dir = tmp_path / "datasets"
    rc, _, err = _run(
        [
            "build-dataset",
            "--since-days",
            "365",
            "--output-dir",
            str(out_dir),
        ]
    )
    # No sessions at all → reported as no trajectories.
    assert rc == 1
    assert "no trajectories" in err.lower()


# ---- run subcommand ----------------------------------------------------


def test_train_run_subcommand_invokes_lora_and_dpo(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    sft = tmp_path / "sft.jsonl"
    sft.write_text('{"messages": []}\n', encoding="utf-8")
    dpo = tmp_path / "dpo.jsonl"
    dpo.write_text('{"prompt": "p", "chosen": "c", "rejected": "r"}\n', encoding="utf-8")

    calls: list[str] = []

    def fake_lora(run, **kwargs):
        calls.append("lora")
        # Simulate adapter on disk so find_lora_adapter succeeds.
        adapter = Path(run.output_dir) / "lora_out"
        adapter.mkdir(parents=True, exist_ok=True)
        return 0

    def fake_dpo(run, sft_lora, **kwargs):
        calls.append("dpo")
        return 0

    def fake_export(lora_path, *, ollama_name, **kwargs):
        calls.append("export")
        return 0

    monkeypatch.setattr(train_cli, "run_lora", fake_lora)
    monkeypatch.setattr(train_cli, "run_dpo", fake_dpo)
    monkeypatch.setattr(train_cli, "export_to_gguf", fake_export)
    monkeypatch.setattr(train_cli, "ensure_ollama_on_path", lambda: True)

    out_dir = tmp_path / "run-out"
    rc, stdout, _ = _run(
        [
            "run",
            "--base-model",
            "Qwen/Qwen2.5-Coder-1.5B",
            "--sft-dataset",
            str(sft),
            "--dpo-dataset",
            str(dpo),
            "--epochs",
            "1",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0
    assert calls == ["lora", "dpo", "export"]
    assert "training complete" in stdout.lower()


def test_train_run_with_no_dpo_pairs_skips_dpo(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    sft = tmp_path / "sft.jsonl"
    sft.write_text("{}\n", encoding="utf-8")

    calls: list[str] = []

    def fake_lora(run, **kwargs):
        calls.append("lora")
        (Path(run.output_dir) / "lora_out").mkdir(parents=True)
        return 0

    def fake_dpo(*args, **kwargs):
        calls.append("dpo")
        return 0

    def fake_export(*args, **kwargs):
        calls.append("export")
        return 0

    monkeypatch.setattr(train_cli, "run_lora", fake_lora)
    monkeypatch.setattr(train_cli, "run_dpo", fake_dpo)
    monkeypatch.setattr(train_cli, "export_to_gguf", fake_export)
    monkeypatch.setattr(train_cli, "ensure_ollama_on_path", lambda: True)

    rc, _, _ = _run(
        [
            "run",
            "--base-model",
            "Qwen/x",
            "--sft-dataset",
            str(sft),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 0
    assert "dpo" not in calls  # skipped


def test_train_run_lora_failure_returns_exit_code(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    sft = tmp_path / "sft.jsonl"
    sft.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(train_cli, "run_lora", lambda run, **k: 17)
    rc, _, err = _run(
        [
            "run",
            "--base-model",
            "x",
            "--sft-dataset",
            str(sft),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 17
    assert "LoRA training failed" in err


def test_train_run_missing_sft_dataset(isolated_home: Path):
    rc, _, err = _run(
        [
            "run",
            "--base-model",
            "x",
            "--sft-dataset",
            "/nonexistent/path.jsonl",
        ]
    )
    assert rc == 2
    assert "not found" in err


# ---- status subcommand -------------------------------------------------


def test_status_empty(isolated_home: Path):
    rc, stdout, _ = _run(["status"])
    assert rc == 0
    assert "no training runs" in stdout


def test_status_shows_last_run(isolated_home: Path):
    # Seed the state file.
    state_path = train_cli.TRAINING_STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "timestamp": "2026-05-16T12:00:00+00:00",
                        "base_model": "Qwen/x",
                        "output_name": "qwen-athena-1",
                        "output_dir": "/tmp/out",
                        "sft_dataset": "/tmp/sft.jsonl",
                        "dpo_dataset": None,
                        "exit_codes": {"sft": 0, "dpo": None, "export": 0, "register": 0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rc, stdout, _ = _run(["status"])
    assert rc == 0
    assert "qwen-athena-1" in stdout
    assert "Qwen/x" in stdout


# ---- _next_output_name -------------------------------------------------


def test_next_output_name_strips_org_prefix(isolated_home: Path):
    name = train_cli._next_output_name("Qwen/Qwen2.5-Coder-1.5B")
    assert name == "Qwen2.5-Coder-1.5B-athena-1"


def test_next_output_name_increments(isolated_home: Path):
    state_path = train_cli.TRAINING_STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "runs": [
                    {"output_name": "X-athena-1"},
                    {"output_name": "X-athena-2"},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert train_cli._next_output_name("X") == "X-athena-3"
