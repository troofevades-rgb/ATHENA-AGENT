"""run_generation orchestrator tests (T6-05.1).

Uses a stub backend that drives the submit → poll → fetch
cycle deterministically. No vendor / network / async — the
orchestrator is sync; tests inject ``sleep`` so polls don't
actually pause.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.videogen.job import (
    CostEstimate,
    GenerationRequest,
    GenerationResult,
    JobHandle,
    run_generation,
)


# ---------------------------------------------------------------------------
# Stub backend
# ---------------------------------------------------------------------------


class _StubBackend:
    """Deterministic backend for orchestrator tests."""

    name = "stub_video"

    def __init__(
        self,
        *,
        estimate: CostEstimate | None = None,
        poll_sequence: list[dict] | None = None,
        fetch_payload: bytes = b"fake video bytes",
        submit_raises: Exception | None = None,
        fetch_raises: Exception | None = None,
        estimate_raises: Exception | None = None,
    ):
        self._estimate = estimate or CostEstimate(seconds_est=5.0, cost_est=0.1)
        self._poll_sequence = list(poll_sequence or [{"status": "done"}])
        self._poll_idx = 0
        self._fetch_payload = fetch_payload
        self._submit_raises = submit_raises
        self._fetch_raises = fetch_raises
        self._estimate_raises = estimate_raises
        self.submit_calls: list[GenerationRequest] = []
        self.fetch_calls: list[JobHandle] = []

    def estimate(self, request: GenerationRequest) -> CostEstimate:
        if self._estimate_raises is not None:
            raise self._estimate_raises
        return self._estimate

    def submit(self, request: GenerationRequest) -> JobHandle:
        if self._submit_raises is not None:
            raise self._submit_raises
        self.submit_calls.append(request)
        return JobHandle(backend=self.name, job_id="job-1", status="pending")

    def poll(self, handle: JobHandle) -> JobHandle:
        idx = min(self._poll_idx, len(self._poll_sequence) - 1)
        self._poll_idx += 1
        state = dict(self._poll_sequence[idx])
        handle.status = state.get("status", "running")
        handle.progress = float(state.get("progress", 0.0))
        handle.error = state.get("error")
        return handle

    def fetch(self, handle: JobHandle, *, out_dir: Path) -> Path:
        if self._fetch_raises is not None:
            raise self._fetch_raises
        self.fetch_calls.append(handle)
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{handle.job_id}.mp4"
        target.write_bytes(self._fetch_payload)
        return target


def _cfg(tmp_path: Path, **overrides) -> SimpleNamespace:
    """Post-R4 stage 5: video_* generation fields moved into the nested
    cfg.video_generation dataclass."""
    legacy_to_nested = {
        "video_confirm_over_seconds": "confirm_over_seconds",
        "video_confirm_over_cost": "confirm_over_cost",
        "video_output_dir": "output_dir",
        "video_poll_interval_s": "poll_interval_s",
        "video_backend": "backend",
        "video_backend_prefer": "backend_prefer",
        "video_generation_enabled": "enabled",
    }
    vg = dict(
        enabled=True,
        backend=None,
        backend_prefer="local",
        confirm_over_seconds=60.0,
        confirm_over_cost=1.0,
        output_dir=str(tmp_path / "videos"),
        poll_interval_s=0.001,
    )
    top: dict = {}
    for k, v in overrides.items():
        if k in legacy_to_nested:
            vg[legacy_to_nested[k]] = v
        elif k in vg:
            vg[k] = v
        else:
            top[k] = v
    return SimpleNamespace(
        video_generation=SimpleNamespace(**vg),
        **top,
    )


def _no_sleep(_s: float) -> None:
    """Replace time.sleep with a no-op so tests don't actually
    pause during polling."""


# ---------------------------------------------------------------------------
# Cheap-and-fast path — no confirm, runs to done
# ---------------------------------------------------------------------------


def test_job_polls_until_done(tmp_path: Path):
    """Backend reports pending → running → running → done; the
    orchestrator polls until done then fetches."""
    backend = _StubBackend(
        poll_sequence=[
            {"status": "pending"},
            {"status": "running", "progress": 0.5},
            {"status": "running", "progress": 0.9},
            {"status": "done", "progress": 1.0},
        ]
    )
    request = GenerationRequest(
        mode="text_to_video", prompt="a paper boat", duration_s=5.0
    )
    result = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        sleep=_no_sleep,
    )
    assert result.status == "done"
    assert result.path is not None
    assert result.path.exists()
    assert result.sha256 is not None
    assert len(result.sha256) == 64
    assert result.backend == "stub_video"
    assert len(backend.fetch_calls) == 1


def test_output_hash_logged(tmp_path: Path):
    """A done job lands in the media_log.jsonl in the output
    directory alongside the file."""
    backend = _StubBackend(fetch_payload=b"clip-bytes-here")
    request = GenerationRequest(
        mode="text_to_video", prompt="hello", duration_s=3.0
    )
    result = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        sleep=_no_sleep,
    )
    log_path = result.path.parent / "media_log.jsonl"
    assert log_path.exists()
    rows = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1
    row = json.loads(rows[0])
    assert row["kind"] == "video_generation"
    assert row["sha256"] == result.sha256
    assert row["backend"] == "stub_video"
    assert row["path"] == str(result.path)
    assert row["duration_s"] == 3.0
    assert row["prompt"] == "hello"


# ---------------------------------------------------------------------------
# Cost guard
# ---------------------------------------------------------------------------


def test_declined_when_confirm_false(tmp_path: Path):
    """An over-threshold job whose confirm returns False is
    declined — submit NEVER fires."""
    backend = _StubBackend(estimate=CostEstimate(seconds_est=120.0, cost_est=5.0))
    request = GenerationRequest(mode="text_to_video", prompt="long one")
    result = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        confirm=lambda est, req: False,
        sleep=_no_sleep,
    )
    assert result.status == "declined"
    assert result.estimate is not None
    assert result.estimate.seconds_est == 120.0
    # CRITICAL: submit never called.
    assert backend.submit_calls == []
    # And no fetch either.
    assert backend.fetch_calls == []


def test_approved_when_confirm_true_submits_and_completes(tmp_path: Path):
    """Over threshold + approve → submit + run to done."""
    backend = _StubBackend(estimate=CostEstimate(seconds_est=120.0, cost_est=5.0))
    request = GenerationRequest(mode="text_to_video", prompt="long approved")
    result = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        confirm=lambda est, req: True,
        sleep=_no_sleep,
    )
    assert result.status == "done"
    assert len(backend.submit_calls) == 1


def test_under_threshold_skips_confirm_callback(tmp_path: Path):
    """A small / cheap job → confirm callback is NEVER even
    asked. Saves the user the prompt + makes tests cleaner."""
    callback_calls: list = []

    def _confirm(est, req):
        callback_calls.append((est, req))
        return True

    backend = _StubBackend(estimate=CostEstimate(seconds_est=5.0, cost_est=0.1))
    request = GenerationRequest(mode="text_to_video", prompt="quick")
    result = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        confirm=_confirm,
        sleep=_no_sleep,
    )
    assert result.status == "done"
    assert callback_calls == []  # never asked


def test_default_confirm_is_default_deny(tmp_path: Path):
    """No confirm callback supplied → default_deny → an
    over-threshold job is declined automatically. Preserves
    the "never silently spend" invariant in the absence of a
    UI."""
    backend = _StubBackend(estimate=CostEstimate(seconds_est=120.0, cost_est=5.0))
    request = GenerationRequest(mode="text_to_video", prompt="x")
    result = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        # No confirm= passed.
        sleep=_no_sleep,
    )
    assert result.status == "declined"
    assert backend.submit_calls == []


def test_confirm_callback_raises_treated_as_denial(tmp_path: Path):
    """A crashed confirm UI must NOT open-fail — same contract
    as T6-04's permission gate."""

    def _explode(est, req):
        raise RuntimeError("UI dead")

    backend = _StubBackend(estimate=CostEstimate(seconds_est=120.0, cost_est=5.0))
    request = GenerationRequest(mode="text_to_video", prompt="x")
    result = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        confirm=_explode,
        sleep=_no_sleep,
    )
    assert result.status == "declined"
    assert backend.submit_calls == []


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_estimate_failure_returns_error(tmp_path: Path):
    backend = _StubBackend(estimate_raises=RuntimeError("backend dead"))
    request = GenerationRequest(mode="text_to_video", prompt="x")
    result = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        sleep=_no_sleep,
    )
    assert result.status == "error"
    assert "backend dead" in result.error


def test_submit_failure_returns_error_no_poll(tmp_path: Path):
    backend = _StubBackend(submit_raises=RuntimeError("submit boom"))
    request = GenerationRequest(mode="text_to_video", prompt="x")
    result = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        sleep=_no_sleep,
    )
    assert result.status == "error"
    assert "submit boom" in result.error


def test_backend_reports_failure_status(tmp_path: Path):
    """Backend's poll returns status=failed → error result with
    the backend's error message surfaced."""
    backend = _StubBackend(
        poll_sequence=[
            {"status": "running"},
            {"status": "failed", "error": "model OOM"},
        ]
    )
    request = GenerationRequest(mode="text_to_video", prompt="x")
    result = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        sleep=_no_sleep,
    )
    assert result.status == "error"
    assert "model OOM" in result.error


def test_fetch_failure_returns_error(tmp_path: Path):
    backend = _StubBackend(fetch_raises=RuntimeError("storage full"))
    request = GenerationRequest(mode="text_to_video", prompt="x")
    result = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        sleep=_no_sleep,
    )
    assert result.status == "error"
    assert "storage full" in result.error


# ---------------------------------------------------------------------------
# Frame check (T4-01 optional)
# ---------------------------------------------------------------------------


def test_frame_check_optional(tmp_path: Path):
    """vision_check=None → no frame_check field in the result.
    Passes a vision_check → result.frame_check carries the
    summary."""
    backend = _StubBackend()
    request = GenerationRequest(mode="text_to_video", prompt="x")
    # No vision_check.
    r1 = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        sleep=_no_sleep,
    )
    assert r1.frame_check is None

    # With vision_check.
    def _check(p: Path) -> str:
        return f"frame OK: {p.suffix}"

    backend = _StubBackend()
    r2 = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        vision_check=_check,
        sleep=_no_sleep,
    )
    assert r2.frame_check == "frame OK: .mp4"


def test_frame_check_exception_does_not_break(tmp_path: Path):
    """A vision-check exception → no frame_check in result, but
    the generation itself still succeeds. The check is advisory."""

    def _crashy(p: Path) -> str:
        raise RuntimeError("vision broke")

    backend = _StubBackend()
    request = GenerationRequest(mode="text_to_video", prompt="x")
    result = run_generation(
        request,
        backend=backend,
        cfg=_cfg(tmp_path),
        vision_check=_crashy,
        sleep=_no_sleep,
    )
    assert result.status == "done"
    assert result.frame_check is None
