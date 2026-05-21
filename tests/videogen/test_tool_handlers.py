"""End-to-end tests for video_generate + animate_image tools (T6-05.3).

Stubs the cfg + the broker resolution so a single test exercises
the full pipeline (cfg gate → broker resolve → submit → poll →
fetch → hash-log) using the in-repo stub_local backend's actual
implementation. No vendor, no network.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.videogen import tools as tools_mod


def _cfg(tmp_path: Path, **overrides) -> SimpleNamespace:
    base = dict(
        video_generation_enabled=True,
        video_backend_prefer="local",
        media_backend_prefer="local",
        video_confirm_over_seconds=60.0,
        video_confirm_over_cost=1.0,
        video_output_dir=str(tmp_path / "videos"),
        video_poll_interval_s=0.001,
        profile="default",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Disabled by default
# ---------------------------------------------------------------------------


def test_video_generate_refuses_when_disabled(monkeypatch, tmp_path: Path):
    """cfg.video_generation_enabled=False → not_enabled payload,
    NO backend resolution attempted."""
    monkeypatch.setattr(
        tools_mod, "_load_cfg",
        lambda: _cfg(tmp_path, video_generation_enabled=False),
    )

    resolve_calls = {"n": 0}

    def _spy_resolve(cfg):
        resolve_calls["n"] += 1
        return None

    monkeypatch.setattr(tools_mod, "resolve_backend", _spy_resolve)
    out = json.loads(tools_mod.video_generate(prompt="x", duration_s=2.0))
    assert out["status"] == "not_enabled"
    assert resolve_calls["n"] == 0


def test_animate_image_refuses_when_disabled(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        tools_mod, "_load_cfg",
        lambda: _cfg(tmp_path, video_generation_enabled=False),
    )
    img = tmp_path / "src.png"
    img.write_bytes(b"img")
    out = json.loads(
        tools_mod.animate_image(image_path=str(img), motion_prompt="zoom")
    )
    assert out["status"] == "not_enabled"


# ---------------------------------------------------------------------------
# Empty / invalid args
# ---------------------------------------------------------------------------


def test_video_generate_requires_prompt(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))
    out = json.loads(tools_mod.video_generate(prompt="   "))
    assert out["status"] == "rejected"
    assert "prompt" in out["reason"]


def test_animate_image_requires_source(monkeypatch, tmp_path: Path):
    """Missing image_path → rejected; nonexistent file →
    rejected; empty motion_prompt → rejected."""
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))

    out1 = json.loads(tools_mod.animate_image(image_path="", motion_prompt="x"))
    assert out1["status"] == "rejected"
    assert "image_path" in out1["reason"]

    out2 = json.loads(
        tools_mod.animate_image(
            image_path=str(tmp_path / "missing.png"), motion_prompt="x"
        )
    )
    assert out2["status"] == "rejected"
    assert "does not exist" in out2["reason"]

    img = tmp_path / "src.png"
    img.write_bytes(b"img")
    out3 = json.loads(
        tools_mod.animate_image(image_path=str(img), motion_prompt="")
    )
    assert out3["status"] == "rejected"
    assert "motion_prompt" in out3["reason"]


# ---------------------------------------------------------------------------
# No-backend payload
# ---------------------------------------------------------------------------


def test_video_generate_no_backend(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))
    monkeypatch.setattr(tools_mod, "resolve_backend", lambda cfg: None)
    out = json.loads(tools_mod.video_generate(prompt="anything"))
    assert out["status"] == "not_configured"
    assert "no video-generation backend" in out["reason"]


# ---------------------------------------------------------------------------
# Happy path via stub backend
# ---------------------------------------------------------------------------


def test_video_generate_writes_output(monkeypatch, tmp_path: Path):
    """End-to-end: cfg enabled + stub backend resolves + run
    succeeds → file written + sha + audit."""
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))

    out = json.loads(
        tools_mod.video_generate(
            prompt="a paper boat", duration_s=3.0
        )
    )
    assert out["status"] == "done"
    assert out["backend"] == "stub_video_local"
    assert "path" in out
    assert Path(out["path"]).exists()
    assert len(out["sha256"]) == 64
    assert out["duration_s"] == 3.0
    # Media log alongside.
    log_path = Path(out["path"]).parent / "media_log.jsonl"
    assert log_path.exists()


def test_animate_image_writes_output(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(tools_mod, "_load_cfg", lambda: _cfg(tmp_path))
    img = tmp_path / "src.png"
    img.write_bytes(b"fake-image-bytes")
    out = json.loads(
        tools_mod.animate_image(
            image_path=str(img),
            motion_prompt="slow zoom in",
            duration_s=2.0,
        )
    )
    assert out["status"] == "done"
    assert out["backend"] == "stub_video_local"
    assert Path(out["path"]).exists()
    assert out["duration_s"] == 2.0


# ---------------------------------------------------------------------------
# Cost-guard end-to-end through the tool surface
# ---------------------------------------------------------------------------


def test_video_generate_long_job_declined_by_default(monkeypatch, tmp_path: Path):
    """A long-duration request (over the seconds threshold) +
    no confirm UI plumbed → default_deny kicks in →
    status=declined, no file produced."""
    monkeypatch.setattr(
        tools_mod, "_load_cfg",
        lambda: _cfg(tmp_path, video_confirm_over_seconds=10.0),
    )
    out = json.loads(
        tools_mod.video_generate(prompt="long clip", duration_s=120.0)
    )
    assert out["status"] == "declined"
    assert out["estimate"]["seconds_est"] == 120.0
    # And no media file was written for the declined job.
    videos_dir = tmp_path / "videos"
    if videos_dir.exists():
        files = [p for p in videos_dir.iterdir() if p.suffix == ".mp4"]
        assert files == []
