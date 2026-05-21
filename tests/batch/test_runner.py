"""T7-02.1 — batch runner core tests.

Stub run_fn so the suite doesn't touch a real Agent / model.
Every test exercises a single load-bearing property of the
batch engine.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.batch.manifest import (
    BatchEntry,
    BatchManifest,
    ManifestEntry,
    mint_batch_id,
)
from athena.batch.runner import (
    _safe_filename,
    batch_run,
    parse_tasks_file,
)
from athena.headless.result import RunResult


# ---------------------------------------------------------------
# parse_tasks_file
# ---------------------------------------------------------------


def test_parse_tasks_file_basic(tmp_path: Path):
    f = tmp_path / "tasks.jsonl"
    f.write_text(
        '{"task": "first"}\n'
        '{"task": "second", "run_id": "r-fixed"}\n'
        '{"task": "third", "cwd": "/tmp", "timeout_s": 30.5, "model": "gpt-x"}\n',
        encoding="utf-8",
    )
    entries = parse_tasks_file(f)
    assert len(entries) == 3
    assert entries[0].task == "first"
    assert entries[0].run_id is None
    assert entries[1].run_id == "r-fixed"
    assert entries[2].cwd == "/tmp"
    assert entries[2].timeout_s == 30.5
    assert entries[2].model == "gpt-x"


def test_parse_tasks_file_skips_blank_and_comment_lines(tmp_path: Path):
    f = tmp_path / "tasks.jsonl"
    f.write_text(
        "# a comment\n"
        "\n"
        '{"task": "real one"}\n'
        "   \n"
        "# another comment\n"
        '{"task": "real two"}\n',
        encoding="utf-8",
    )
    entries = parse_tasks_file(f)
    assert [e.task for e in entries] == ["real one", "real two"]


def test_parse_tasks_file_rejects_missing_task(tmp_path: Path):
    f = tmp_path / "tasks.jsonl"
    f.write_text('{"task": ""}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        parse_tasks_file(f)


def test_parse_tasks_file_rejects_bad_json(tmp_path: Path):
    f = tmp_path / "tasks.jsonl"
    f.write_text(
        '{"task": "ok"}\n'
        'not json here\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="line 2.*not valid JSON"):
        parse_tasks_file(f)


def test_parse_tasks_file_rejects_non_object(tmp_path: Path):
    f = tmp_path / "tasks.jsonl"
    f.write_text('["a", "b"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="expected an object"):
        parse_tasks_file(f)


def test_parse_tasks_file_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_tasks_file("/no/such/tasks.jsonl")


# ---------------------------------------------------------------
# _safe_filename
# ---------------------------------------------------------------


def test_safe_filename_passes_through_clean_ids():
    assert _safe_filename("r-abc123def456") == "r-abc123def456"


def test_safe_filename_replaces_unsafe_chars():
    assert _safe_filename("batch/2026-01-01") == "batch_2026-01-01"
    assert _safe_filename("hello world!") == "hello_world"
    assert _safe_filename("../etc/passwd") == "etc_passwd"


def test_safe_filename_never_empty():
    """Even an all-unsafe run_id falls back to the original so
    filenames are never the empty string."""
    assert _safe_filename("///") != ""


# ---------------------------------------------------------------
# mint_batch_id
# ---------------------------------------------------------------


def test_mint_batch_id_format():
    bid = mint_batch_id()
    assert bid.startswith("b-")
    assert len(bid) == 2 + 12


# ---------------------------------------------------------------
# Stub run_fn — minimal RunResult-shape for the runner to consume
# ---------------------------------------------------------------


def _stub_run_fn(
    *, task, cfg, workspace, model, run_id, timeout_s,
    status: str = "ok",
    error: str | None = None,
    duration_s: float = 0.5,
):
    """Build a RunResult mimicking run_headless. The caller's
    factory closure can customise status / error / duration."""
    return RunResult(
        run_id=run_id or "r-stub",
        status=status,  # type: ignore[arg-type]
        started_at="2026-05-21T00:00:00.000000Z",
        finished_at="2026-05-21T00:00:01.000000Z",
        duration_s=duration_s,
        task=task,
        workspace=str(workspace),
        model=model or cfg.model,
        profile="default",
        session_id="s-stub-1",
        tool_calls=[{"name": "Read", "count": 2}],
        tokens={"prompt": 10, "completion": 5,
                "cache_read": 0, "cache_creation": 0},
        cost_est=0.0,
        assistant_text=f"answer for: {task}",
        error=error,
    )


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(model="stub-model", profile="default")


# ---------------------------------------------------------------
# batch_run — happy paths
# ---------------------------------------------------------------


def test_batch_run_writes_per_run_envelope_and_manifest(tmp_path: Path):
    entries = [
        BatchEntry(task="first task"),
        BatchEntry(task="second task", run_id="r-explicit"),
    ]
    out = tmp_path / "out"
    manifest = batch_run(
        entries, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=out,
        run_fn=_stub_run_fn,
    )
    # manifest.json exists + valid + per-run files all there.
    manifest_path = out / "manifest.json"
    assert manifest_path.exists()
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert m["total"] == 2
    assert m["completed"] == 2
    assert m["skipped"] == 0
    assert m["by_status"] == {"ok": 2}
    # Per-run envelope files exist.
    assert (out / "r-explicit.json").exists()
    # Auto-minted run_id has r- prefix.
    auto_files = [p for p in out.glob("r-*.json") if p.name != "r-explicit.json"]
    assert len(auto_files) == 1


def test_batch_run_envelope_content_matches_runresult(tmp_path: Path):
    entries = [BatchEntry(task="x", run_id="r-payload-check")]
    batch_run(
        entries, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out",
        run_fn=_stub_run_fn,
    )
    env = json.loads((tmp_path / "out" / "r-payload-check.json").read_text())
    # Required RunResult fields all present in the envelope.
    assert env["status"] == "ok"
    assert env["task"] == "x"
    assert env["assistant_text"] == "answer for: x"


def test_batch_run_per_entry_overrides_propagate(tmp_path: Path):
    """An entry's cwd / model / timeout_s overrides the batch
    default. The stub captures what it was called with."""
    received: list[dict[str, Any]] = []

    def _capture(*, task, cfg, workspace, model, run_id, timeout_s):
        received.append({
            "task": task, "workspace": str(workspace),
            "model": model, "timeout_s": timeout_s,
        })
        return _stub_run_fn(
            task=task, cfg=cfg, workspace=workspace,
            model=model, run_id=run_id, timeout_s=timeout_s,
        )

    sub = tmp_path / "sub"
    sub.mkdir()
    entries = [
        BatchEntry(task="t1"),
        BatchEntry(task="t2", cwd=str(sub),
                   model="other-model", timeout_s=99.0),
    ]
    batch_run(
        entries, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out",
        run_fn=_capture,
    )
    assert received[0]["workspace"] == str(tmp_path)
    assert received[0]["model"] is None
    assert received[0]["timeout_s"] is None
    assert received[1]["workspace"] == str(sub)
    assert received[1]["model"] == "other-model"
    assert received[1]["timeout_s"] == 99.0


# ---------------------------------------------------------------
# Mixed-status accumulation
# ---------------------------------------------------------------


def test_batch_run_aggregates_status_counts(tmp_path: Path):
    """Each entry returns a different status; the manifest's
    by_status histogram is populated correctly + the entries
    list keeps insertion order."""
    statuses = ["ok", "error", "ok", "timeout", "ok"]

    def _per_entry(*, task, cfg, workspace, model, run_id, timeout_s):
        idx = int(task[1:])  # task is "T0", "T1", ...
        st = statuses[idx]
        err = "boom" if st == "error" else None
        return _stub_run_fn(
            task=task, cfg=cfg, workspace=workspace,
            model=model, run_id=run_id, timeout_s=timeout_s,
            status=st, error=err,
        )

    entries = [BatchEntry(task=f"T{i}", run_id=f"r-{i:03d}") for i in range(5)]
    m = batch_run(
        entries, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out",
        run_fn=_per_entry,
    )
    assert m.by_status == {"ok": 3, "error": 1, "timeout": 1}
    assert [e.run_id for e in m.entries] == [f"r-{i:03d}" for i in range(5)]
    # Error rows carry an error_excerpt.
    error_row = next(e for e in m.entries if e.status == "error")
    assert error_row.error_excerpt == "boom"


# ---------------------------------------------------------------
# Resume-safety: skip already-done entries
# ---------------------------------------------------------------


def test_batch_run_skips_existing_envelopes(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    # Pre-existing envelope for r-existing.
    (out / "r-existing.json").write_text(
        json.dumps({
            "run_id": "r-existing", "status": "ok", "exit_code": 0,
            "duration_s": 1.0, "task": "skipped", "error": None,
        }),
        encoding="utf-8",
    )

    seen_tasks: list[str] = []

    def _spy(*, task, **kw):
        seen_tasks.append(task)
        return _stub_run_fn(task=task, **kw)

    entries = [
        BatchEntry(task="will-run", run_id="r-new"),
        BatchEntry(task="will-skip", run_id="r-existing"),
    ]
    m = batch_run(
        entries, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=out, run_fn=_spy,
    )
    # Only the new entry ran.
    assert seen_tasks == ["will-run"]
    assert m.completed == 1
    assert m.skipped == 1
    # Both appear in the manifest in input order.
    assert [e.run_id for e in m.entries] == ["r-new", "r-existing"]


def test_batch_run_force_reruns_existing(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "r-existing.json").write_text(
        json.dumps({
            "run_id": "r-existing", "status": "ok", "exit_code": 0,
            "duration_s": 1.0, "task": "old", "error": None,
        }),
        encoding="utf-8",
    )

    ran: list[str] = []
    def _spy(*, task, **kw):
        ran.append(task)
        return _stub_run_fn(task=task, **kw)

    entries = [BatchEntry(task="new-run", run_id="r-existing")]
    m = batch_run(
        entries, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=out, run_fn=_spy,
        force=True,
    )
    assert ran == ["new-run"]
    assert m.skipped == 0
    # Envelope overwritten with the new task.
    env = json.loads((out / "r-existing.json").read_text())
    assert env["task"] == "new-run"


# ---------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------


def test_batch_run_progress_callback_fires_per_entry(tmp_path: Path):
    entries = [BatchEntry(task=f"T{i}") for i in range(4)]
    progress_log: list[tuple[str, int, int]] = []
    def _progress(me: ManifestEntry, done: int, total: int):
        progress_log.append((me.status, done, total))
    batch_run(
        entries, cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out",
        run_fn=_stub_run_fn,
        progress=_progress,
    )
    assert progress_log == [
        ("ok", 1, 4),
        ("ok", 2, 4),
        ("ok", 3, 4),
        ("ok", 4, 4),
    ]


def test_batch_run_progress_fires_for_skipped(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "r-x.json").write_text(
        json.dumps({
            "run_id": "r-x", "status": "ok", "exit_code": 0,
            "duration_s": 0.0, "task": "done", "error": None,
        }),
        encoding="utf-8",
    )
    progress_log: list[str] = []
    batch_run(
        [BatchEntry(task="done", run_id="r-x")],
        cfg=_cfg(), workspace_default=tmp_path,
        output_dir=out, run_fn=_stub_run_fn,
        progress=lambda me, _d, _t: progress_log.append(me.status),
    )
    # Skipped entries still call progress (callers want a
    # "done/total" tick regardless).
    assert progress_log == ["ok"]


# ---------------------------------------------------------------
# Batch ID
# ---------------------------------------------------------------


def test_batch_id_minted_when_absent(tmp_path: Path):
    m = batch_run(
        [BatchEntry(task="t")],
        cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", run_fn=_stub_run_fn,
    )
    assert m.batch_id.startswith("b-")


def test_batch_id_passed_through(tmp_path: Path):
    m = batch_run(
        [BatchEntry(task="t")],
        cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", run_fn=_stub_run_fn,
        batch_id="b-my-batch-001",
    )
    assert m.batch_id == "b-my-batch-001"


# ---------------------------------------------------------------
# Empty batch
# ---------------------------------------------------------------


def test_empty_batch_writes_empty_manifest(tmp_path: Path):
    m = batch_run(
        [], cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", run_fn=_stub_run_fn,
    )
    assert m.total == 0
    assert m.completed == 0
    assert m.entries == []
    # Manifest still written so a downstream consumer can see
    # "this batch ran but had no entries".
    assert (tmp_path / "out" / "manifest.json").exists()


# ---------------------------------------------------------------
# Excerpt limits
# ---------------------------------------------------------------


def test_long_task_excerpted_in_manifest(tmp_path: Path):
    long_task = "x" * 500
    m = batch_run(
        [BatchEntry(task=long_task, run_id="r-long")],
        cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", run_fn=_stub_run_fn,
    )
    assert len(m.entries[0].task_excerpt) <= 240
    assert m.entries[0].task_excerpt.endswith("…")


def test_long_error_excerpted_in_manifest(tmp_path: Path):
    long_err = "boom " * 100
    def _err_stub(**kw):
        return _stub_run_fn(**kw, status="error", error=long_err)
    m = batch_run(
        [BatchEntry(task="t", run_id="r-err")],
        cfg=_cfg(), workspace_default=tmp_path,
        output_dir=tmp_path / "out", run_fn=_err_stub,
    )
    assert m.entries[0].error_excerpt is not None
    assert len(m.entries[0].error_excerpt) <= 200
