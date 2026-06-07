"""ffprobe-backed container / codec / encoder inspection (T4-02.3).

Four call sites:

  ffprobe_json(path)            full ffprobe JSON dump
  codec_summary(probe)          one-row codec/profile/dims/fps/bitrate
  encoder_fingerprint(probe)    x264/x265 tag detection + handler
                                names; HEDGED interpretation strings
  gop_structure(path)           I/P/B frame-type pattern + keyframe
                                intervals (first N frames)

Every function is defensive — a missing ffprobe binary raises
:class:`FFprobeMissing` with a clear message; non-zero exit /
malformed JSON returns the documented "no data" shape rather
than crashing. The analyze layer above uses these as inputs to
the two-layer report and stays composable even when the host
lacks ffprobe (atom-only mode still works — see T4-02.2).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)


class FFprobeMissing(RuntimeError):
    """Raised when ffprobe is not on PATH or refuses to run."""


def ffprobe_json(
    path: Path | str,
    *,
    ffprobe: str = "ffprobe",
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Run ``ffprobe -show_format -show_streams`` on ``path`` and
    return the parsed JSON.

    Raises :class:`FFprobeMissing` when the binary isn't on PATH.
    Returns ``{}`` when ffprobe runs but emits no JSON (an
    unreadable file produces empty stdout + a warning on stderr;
    we report empty rather than raise so the analyze layer can
    surface "no probe data" cleanly)."""
    if not shutil.which(ffprobe):
        raise FFprobeMissing(
            f"{ffprobe!r} not found on PATH — install ffmpeg "
            "(brew install ffmpeg / apt install ffmpeg / "
            "scoop install ffmpeg)"
        )
    try:
        out = subprocess.run(
            [
                ffprobe,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ffprobe timed out on %s", path)
        return {}
    if not out.stdout.strip():
        return {}
    try:
        return cast("dict[str, Any]", json.loads(out.stdout))
    except json.JSONDecodeError:
        logger.warning("ffprobe emitted non-JSON for %s", path)
        return {}


def codec_summary(probe: dict[str, Any]) -> dict[str, Any]:
    """Pull a one-row summary out of a full ffprobe dump.

    Returns ``{"error": "..."}`` shape when the probe has no
    video stream — callers branch on the "error" key.
    """
    video_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    if not video_streams:
        return {"error": "no video stream"}
    v = video_streams[0]
    fmt = probe.get("format", {})
    return {
        "codec_name": v.get("codec_name"),
        "codec_long_name": v.get("codec_long_name"),
        "profile": v.get("profile"),
        "level": v.get("level"),
        "pix_fmt": v.get("pix_fmt"),
        "width": v.get("width"),
        "height": v.get("height"),
        "frame_rate": v.get("r_frame_rate"),
        "bit_rate": v.get("bit_rate") or fmt.get("bit_rate"),
        "duration": fmt.get("duration"),
        "format_name": fmt.get("format_name"),
        "format_tags": fmt.get("tags", {}),
        "stream_tags": v.get("tags", {}),
    }


def encoder_fingerprint(probe: dict[str, Any]) -> dict[str, Any]:
    """Pull encoder tags + handler-name hints, then surface a
    HEDGED interpretation string.

    Two important things:

      - x264 / x265 leave a distinctive ``encoder`` tag in the
        format-level ``tags`` (e.g. "Lavf60.16.100" + "x264 -
        core 164 r3108 ..."). Presence is strong evidence of
        software encoding or remux through ffmpeg.

      - Absence is NOT proof of hardware encoding — many
        camera muxers omit the encoder tag entirely. The
        interpretation string says so explicitly.

    The whole point of the two-layer discipline is that we
    surface signals; the analyst weighs them.
    """
    fmt_tags = probe.get("format", {}).get("tags", {})
    signals: dict[str, Any] = {
        "format_encoder_tag": fmt_tags.get("encoder"),
        "major_brand": fmt_tags.get("major_brand"),
        "compatible_brands": fmt_tags.get("compatible_brands"),
    }
    stream_encoder_tags: list[str] = []
    handler_names: list[str] = []
    for s in probe.get("streams", []):
        tags = s.get("tags", {}) or {}
        if isinstance(tags, dict):
            if "encoder" in tags:
                stream_encoder_tags.append(str(tags["encoder"]))
            if tags.get("handler_name"):
                handler_names.append(str(tags["handler_name"]))
    if stream_encoder_tags:
        signals["stream_encoder_tags"] = stream_encoder_tags
    if handler_names:
        signals["handler_names"] = handler_names

    all_enc_text = " ".join(
        [(signals.get("format_encoder_tag") or "")] + stream_encoder_tags
    ).lower()
    looks_x264 = "x264" in all_enc_text
    looks_x265 = "x265" in all_enc_text or "hevc" in all_enc_text and "x265" in all_enc_text
    signals["software_encoder_likely"] = bool(looks_x264 or looks_x265)

    if looks_x264 or looks_x265:
        signals["interpretation"] = (
            "x264/x265 encoder tag present — the elementary "
            "stream (or this container's stream) was produced "
            "or re-encoded by a software encoder. Common after "
            "an editing or transcoding pass through ffmpeg / "
            "Handbrake / NLE export."
        )
    else:
        signals["interpretation"] = (
            "no software-encoder tag detected — consistent with "
            "hardware / camera encode, BUT absence of a tag is "
            "NOT proof: many camera muxers omit the encoder "
            "field entirely. Cross-check with GOP regularity and "
            "atom ordering before drawing any conclusion."
        )
    return signals


def gop_structure(
    path: Path | str,
    *,
    ffprobe: str = "ffprobe",
    limit: int = 300,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Sample the first ``limit`` frames and report the I/P/B
    pattern + keyframe-interval statistics.

    Hardware encoders and software encoders (x264) differ in
    GOP regularity and B-frame usage. A perfectly regular GOP
    with a software encoder tag tells a different story than an
    irregular GOP consistent with camera capture. The output is
    the raw counts + the interval list — interpretation is up
    to the analyst (or the model reasoning over the report).

    Returns ``{"error": "..."}`` on probe failure rather than
    raising — the analyze layer composes this alongside other
    modes, and one bad sub-mode shouldn't break the whole report.
    """
    if not shutil.which(ffprobe):
        raise FFprobeMissing(f"{ffprobe!r} not found on PATH")
    try:
        out = subprocess.run(
            [
                ffprobe,
                "-v",
                "quiet",
                "-select_streams",
                "v:0",
                "-show_frames",
                "-show_entries",
                "frame=pict_type",
                "-print_format",
                "json",
                "-read_intervals",
                f"%+#{limit}",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"error": "ffprobe timeout"}
    if not out.stdout.strip():
        return {"error": "no frame data"}
    try:
        frames = json.loads(out.stdout).get("frames", [])
    except json.JSONDecodeError:
        return {"error": "non-JSON probe output"}

    types: list[str] = [f.get("pict_type") or "?" for f in frames]
    i_positions = [idx for idx, t in enumerate(types) if t == "I"]
    intervals = [j - i for i, j in zip(i_positions, i_positions[1:])]
    return {
        "frame_types_sample": "".join(types[:120]),
        "frame_types_count": len(types),
        "i_frame_count": types.count("I"),
        "p_frame_count": types.count("P"),
        "b_frame_count": types.count("B"),
        "keyframe_intervals": intervals,
        "regular_gop": (len(set(intervals)) <= 2 if intervals else None),
    }
