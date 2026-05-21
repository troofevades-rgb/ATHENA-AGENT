"""T4-02.5 — video_analyze tool tests.

Pins:
  - Each mode dispatches to the right sub-module
  - inspect keeps container + elementary-stream layers SEPARATE
    (the load-bearing two-layer discipline)
  - inspect's note explicitly says don't-collapse-into-verdict
  - analyze routes frames through the injected provider_fn
  - video_enabled=False short-circuits with no audit row
  - Unknown mode / missing file / missing path rejected
  - Tool registered under the vision toolset
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.video.analyze import VALID_MODES, _run
from tests.video.fixtures import FIXTURES_DIR, have_ffmpeg, have_ffprobe


_NEED_FFPROBE = pytest.mark.skipif(
    not have_ffprobe() or not have_ffmpeg(),
    reason="ffprobe / ffmpeg not on PATH",
)


def _cfg(tmp_path: Path, **overrides: Any) -> SimpleNamespace:
    base = dict(
        profile="default",
        video_enabled=True,
        vision_enabled=True,
        video_ffmpeg_path="ffmpeg",
        video_ffprobe_path="ffprobe",
        video_frames_dir=str(tmp_path / "frames"),
        video_max_frames=200,
        video_default_extract="keyframes",
        video_sampled_interval_s=5.0,
        provider="ollama",
        model="stub-vision-model",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _route_profile_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "athena.video.analyze.profile_dir",
        lambda profile="default": tmp_path,
    )
    yield


# ---------------------------------------------------------------
# Gate + validation
# ---------------------------------------------------------------


def test_video_disabled_short_circuits(tmp_path: Path):
    out = json.loads(_run(
        mode="atoms",
        path=str(FIXTURES_DIR / "sample.mp4") if have_ffmpeg() else "x",
        _cfg=_cfg(tmp_path, video_enabled=False),
    ))
    assert "error" in out
    assert "video_enabled=False" in out["error"]
    # No audit row should have been written.
    assert not (tmp_path / "video_audit.jsonl").exists()


def test_unknown_mode_rejected(tmp_path: Path):
    out = json.loads(_run(
        mode="reverse",
        path="something.mp4",
        _cfg=_cfg(tmp_path),
    ))
    assert "error" in out
    assert "unknown mode" in out["error"]


def test_missing_path_rejected(tmp_path: Path):
    out = json.loads(_run(
        mode="atoms",
        path=None,
        _cfg=_cfg(tmp_path),
    ))
    assert "error" in out
    assert "path is required" in out["error"]


def test_missing_file_rejected(tmp_path: Path):
    out = json.loads(_run(
        mode="atoms",
        path=str(tmp_path / "nope.mp4"),
        _cfg=_cfg(tmp_path),
    ))
    assert "error" in out
    assert "file not found" in out["error"]


def test_unknown_extract_rejected(tmp_path: Path):
    out = json.loads(_run(
        mode="frames",
        path=str(FIXTURES_DIR / "sample.mp4") if have_ffmpeg() else __file__,
        extract="every-other-blue-moon",
        _cfg=_cfg(tmp_path),
    ))
    assert "error" in out
    assert "unknown extract" in out["error"]


# ---------------------------------------------------------------
# Atoms (pure Python — needs no ffmpeg/ffprobe)
# ---------------------------------------------------------------


@pytest.mark.skipif(not have_ffmpeg(),
                    reason="fixtures need ffmpeg to build")
def test_atoms_mode_on_camera_original(tmp_path: Path):
    out = json.loads(_run(
        mode="atoms",
        path=str(FIXTURES_DIR / "camera_original.mp4"),
        _cfg=_cfg(tmp_path),
    ))
    assert out["mode"] == "atoms"
    assert out["moov_before_mdat"] is False
    assert "mdat" in out["atom_order"]


@pytest.mark.skipif(not have_ffmpeg(),
                    reason="fixtures need ffmpeg")
def test_atoms_mode_on_faststart(tmp_path: Path):
    out = json.loads(_run(
        mode="atoms",
        path=str(FIXTURES_DIR / "faststart.mp4"),
        _cfg=_cfg(tmp_path),
    ))
    assert out["moov_before_mdat"] is True
    assert "qt-faststart" in out["interpretation"]


@pytest.mark.skipif(not have_ffmpeg(),
                    reason="fixtures need ffmpeg")
def test_atoms_mode_writes_audit_row(tmp_path: Path):
    _run(
        mode="atoms",
        path=str(FIXTURES_DIR / "sample.mp4"),
        _cfg=_cfg(tmp_path),
    )
    audit = tmp_path / "video_audit.jsonl"
    rows = [json.loads(l) for l in audit.read_text().splitlines() if l.strip()]
    assert rows[0]["mode"] == "atoms"


# ---------------------------------------------------------------
# Probe / GOP / encoder_fingerprint
# ---------------------------------------------------------------


@_NEED_FFPROBE
def test_probe_mode_summary(tmp_path: Path):
    out = json.loads(_run(
        mode="probe",
        path=str(FIXTURES_DIR / "sample.mp4"),
        _cfg=_cfg(tmp_path),
    ))
    assert out["mode"] == "probe"
    assert out["summary"]["codec_name"] in ("h264", "hevc", "h265")


@_NEED_FFPROBE
def test_gop_mode_counts_frames(tmp_path: Path):
    out = json.loads(_run(
        mode="gop",
        path=str(FIXTURES_DIR / "sample.mp4"),
        _cfg=_cfg(tmp_path),
    ))
    assert out["mode"] == "gop"
    assert out["i_frame_count"] >= 1


@_NEED_FFPROBE
def test_encoder_fingerprint_flags_x264(tmp_path: Path):
    out = json.loads(_run(
        mode="encoder_fingerprint",
        path=str(FIXTURES_DIR / "x264_encoded.mp4"),
        _cfg=_cfg(tmp_path),
    ))
    assert out["mode"] == "encoder_fingerprint"
    assert out["software_encoder_likely"] is True


# ---------------------------------------------------------------
# Inspect — the load-bearing two-layer discipline
# ---------------------------------------------------------------


@_NEED_FFPROBE
def test_inspect_keeps_layers_separate(tmp_path: Path):
    """THE load-bearing test: container_layer and
    elementary_stream_layer are present + distinct + populated
    on a real fixture."""
    out = json.loads(_run(
        mode="inspect",
        path=str(FIXTURES_DIR / "faststart.mp4"),
        _cfg=_cfg(tmp_path),
    ))
    assert "container_layer" in out
    assert "elementary_stream_layer" in out
    container = out["container_layer"]
    stream = out["elementary_stream_layer"]
    # Container should mention atom order + faststart.
    assert "atom_order" in container
    assert container["moov_before_mdat"] is True
    # Elementary stream should report codec.
    assert stream["codec_name"] in ("h264", "hevc", "h265")
    # The hedged note must be present + warn against single
    # verdicts.
    assert "SEPARATELY" in out["note"]
    assert "never auto-conclude" in out["note"]


@_NEED_FFPROBE
def test_inspect_atom_layer_for_camera_original(tmp_path: Path):
    out = json.loads(_run(
        mode="inspect",
        path=str(FIXTURES_DIR / "camera_original.mp4"),
        _cfg=_cfg(tmp_path),
    ))
    assert out["container_layer"]["moov_before_mdat"] is False
    assert "camera capture" in out["container_layer"]["remux_interpretation"]


# ---------------------------------------------------------------
# frames + analyze
# ---------------------------------------------------------------


@pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg required")
def test_frames_mode_keyframes(tmp_path: Path):
    out = json.loads(_run(
        mode="frames",
        path=str(FIXTURES_DIR / "sample.mp4"),
        _cfg=_cfg(tmp_path),
    ))
    assert out["mode"] == "frames"
    assert out["extract"] == "keyframes"
    assert out["frame_count"] >= 1
    for fr in out["frames"]:
        assert Path(fr).exists()


@pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg required")
def test_frames_mode_sampled(tmp_path: Path):
    out = json.loads(_run(
        mode="frames",
        path=str(FIXTURES_DIR / "sample.mp4"),
        extract="sampled",
        interval_s=1.0,
        _cfg=_cfg(tmp_path),
    ))
    assert out["extract"] == "sampled"
    assert out["frame_count"] >= 1


@pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg required")
def test_analyze_mode_routes_frames_through_provider(tmp_path: Path):
    """The analyze mode calls provider_fn(frame_path, prompt) for
    each extracted frame. Inject a stub that records calls + a
    sentinel response."""
    seen_paths: list[Path] = []
    def _stub(frame_path: Path, prompt: str) -> str:
        seen_paths.append(frame_path)
        return f"described: {Path(frame_path).name}"

    out = json.loads(_run(
        mode="analyze",
        path=str(FIXTURES_DIR / "sample.mp4"),
        prompt="What is this frame?",
        _cfg=_cfg(tmp_path),
        _provider_fn=_stub,
    ))
    assert out["mode"] == "analyze"
    assert out["frame_count"] >= 1
    assert len(out["analyses"]) == out["frame_count"]
    # Every analysis carries the stub's response shape.
    for a in out["analyses"]:
        assert a["answer"].startswith("described:")
    # The stub was called for every frame.
    assert len(seen_paths) == out["frame_count"]


@pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg required")
def test_analyze_mode_no_provider_returns_frames_only(tmp_path: Path):
    """When the vision provider isn't available, analyze still
    extracts the frames + surfaces a clear error rather than
    crashing."""
    out = json.loads(_run(
        mode="analyze",
        path=str(FIXTURES_DIR / "sample.mp4"),
        _cfg=_cfg(tmp_path, vision_enabled=False),
    ))
    assert out["mode"] == "analyze"
    assert "frames" in out
    assert "error" in out
    assert "vision provider not available" in out["error"]


# ---------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------


def test_tool_registered_in_vision_toolset():
    import athena.tools  # noqa: F401 — trigger registration
    from athena.tools.registry import get_tool
    t = get_tool("video_analyze")
    assert t is not None
    assert t.toolset == "vision"


def test_schema_lists_all_modes():
    import athena.tools  # noqa: F401
    from athena.tools.registry import get_tool
    t = get_tool("video_analyze")
    enum = t.parameters["properties"]["mode"]["enum"]
    assert set(enum) == set(VALID_MODES)
