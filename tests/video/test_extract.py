"""T4-02.4 — frame extraction tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from athena.video.extract import (
    FFmpegMissing,
    extract_keyframes,
    extract_range,
    extract_sampled,
)
from tests.video.fixtures import FIXTURES_DIR, have_ffmpeg


_NEED_FFMPEG = pytest.mark.skipif(
    not have_ffmpeg(),
    reason="ffmpeg not on PATH",
)


# ---------------------------------------------------------------
# missing-ffmpeg paths
# ---------------------------------------------------------------


def test_extract_keyframes_missing_ffmpeg_raises(tmp_path: Path):
    with patch("athena.video.extract.shutil.which", return_value=None):
        with pytest.raises(FFmpegMissing, match="not found on PATH"):
            extract_keyframes("/tmp/x.mp4", tmp_path)


def test_extract_sampled_missing_ffmpeg_raises(tmp_path: Path):
    with patch("athena.video.extract.shutil.which", return_value=None):
        with pytest.raises(FFmpegMissing):
            extract_sampled("/tmp/x.mp4", tmp_path, interval_s=1.0)


def test_extract_range_missing_ffmpeg_raises(tmp_path: Path):
    with patch("athena.video.extract.shutil.which", return_value=None):
        with pytest.raises(FFmpegMissing):
            extract_range("/tmp/x.mp4", tmp_path, start="0", end="1")


def test_extract_sampled_zero_interval_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="interval_s"):
        extract_sampled(
            FIXTURES_DIR / "sample.mp4", tmp_path, interval_s=0,
        )


# ---------------------------------------------------------------
# happy paths (need ffmpeg)
# ---------------------------------------------------------------


@_NEED_FFMPEG
def test_extract_keyframes_produces_frames(tmp_path: Path):
    frames = extract_keyframes(
        FIXTURES_DIR / "sample.mp4", tmp_path / "kf",
    )
    assert len(frames) >= 1
    for f in frames:
        assert f.exists() and f.stat().st_size > 0
        assert f.suffix == ".png"


@_NEED_FFMPEG
def test_extract_sampled_respects_interval(tmp_path: Path):
    """sample.mp4 is 3s. interval=1.0 → ~3 frames."""
    frames = extract_sampled(
        FIXTURES_DIR / "sample.mp4", tmp_path / "s",
        interval_s=1.0,
    )
    assert 1 <= len(frames) <= 5  # some slack for boundary frames


@_NEED_FFMPEG
def test_extract_range_bounded(tmp_path: Path):
    frames = extract_range(
        FIXTURES_DIR / "sample.mp4", tmp_path / "r",
        start="0", end="1",
    )
    assert len(frames) >= 1


@_NEED_FFMPEG
def test_extract_respects_max_frames(tmp_path: Path):
    frames = extract_keyframes(
        FIXTURES_DIR / "sample.mp4", tmp_path / "cap",
        max_frames=1,
    )
    assert len(frames) <= 1
