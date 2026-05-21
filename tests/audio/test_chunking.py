"""T4-04.2 — long-audio chunking + stitching tests.

The load-bearing invariants:

  - chunks cover the full duration with the configured overlap
  - the stitcher de-duplicates segments at chunk seams (so
    words spoken at the overlap region don't appear twice)
  - per-chunk results merge in time order
  - absolute timestamps are correct (chunk_offset_s pushed
    each segment to its file-second position)
  - progress callback fires per chunk with (i, N)
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.audio.job import Segment, TranscribeResult
from athena.audio.tools import (
    _chunk_boundaries,
    _stitch,
    transcribe_track,
)
from tests.audio.conftest import StubAudioBackend, make_wav


# ---------------------------------------------------------------
# _chunk_boundaries
# ---------------------------------------------------------------


def test_short_audio_returns_one_chunk():
    out = _chunk_boundaries(5.0, chunk_s=30.0, overlap_s=2.0)
    assert out == [(0.0, 5.0)]


def test_exactly_at_chunk_size_returns_one_chunk():
    """Edge: when duration equals chunk_s exactly, no second
    chunk needed (the boundary IS the end)."""
    out = _chunk_boundaries(30.0, chunk_s=30.0, overlap_s=2.0)
    assert out == [(0.0, 30.0)]


def test_long_audio_chunks_with_overlap():
    """A 90s file with 30s chunks + 2s overlap → step = 28s.
    Boundaries: (0, 30), (28, 58), (56, 86), (84, 90).
    The last chunk's start (84) is less than 90, but its
    end clamps to duration; no chunk past the file end."""
    out = _chunk_boundaries(90.0, chunk_s=30.0, overlap_s=2.0)
    assert out == [(0.0, 30.0), (28.0, 58.0), (56.0, 86.0), (84.0, 90.0)]
    # Verify overlap between successive chunks.
    for (a_start, a_end), (b_start, _b_end) in zip(out, out[1:]):
        overlap = a_end - b_start
        assert pytest.approx(overlap, abs=0.001) == 2.0


def test_zero_chunk_seconds_returns_one_chunk():
    """Defensive — invalid chunk_s shouldn't loop forever; the
    chunker treats <=0 as "no chunking"."""
    out = _chunk_boundaries(120.0, chunk_s=0.0, overlap_s=2.0)
    assert out == [(0.0, 120.0)]


def test_zero_overlap_chunks_are_contiguous():
    out = _chunk_boundaries(90.0, chunk_s=30.0, overlap_s=0.0)
    assert out == [(0.0, 30.0), (30.0, 60.0), (60.0, 90.0)]


# ---------------------------------------------------------------
# _stitch
# ---------------------------------------------------------------


def test_stitch_passthrough_for_one_chunk():
    r = TranscribeResult(
        segments=[Segment(0.0, 1.0, "hello")],
        language="en", duration=1.0,
    )
    out = _stitch([r], chunk_windows=[(0.0, 1.0)], overlap_s=2.0)
    assert out is r  # short-circuit


def test_stitch_concatenates_distinct_segments():
    chunks = [
        TranscribeResult(
            segments=[Segment(0.0, 5.0, "first chunk text")],
            language="en",
        ),
        TranscribeResult(
            segments=[Segment(28.0, 32.0, "second chunk text")],
            language="en",
        ),
    ]
    windows = [(0.0, 30.0), (28.0, 58.0)]
    out = _stitch(chunks, chunk_windows=windows, overlap_s=2.0)
    assert len(out.segments) == 2
    assert out.segments[0].text == "first chunk text"
    assert out.segments[1].text == "second chunk text"


def test_stitch_dedupes_seam_repeat():
    """A segment that appears at the END of chunk N AND the
    START of chunk N+1 (because it sat in the 2s overlap)
    should be kept once. The dedupe rule: same text +
    timestamp inside the overlap region → drop the duplicate."""
    chunks = [
        TranscribeResult(segments=[
            Segment(25.0, 28.5, "preceding segment"),
            Segment(28.5, 30.0, "in overlap region"),  # at chunk seam
        ]),
        TranscribeResult(segments=[
            # Backend re-emits the overlap segment from this
            # chunk's perspective — same text, similar timestamp.
            Segment(28.5, 30.0, "in overlap region"),  # dup
            Segment(30.0, 32.0, "after seam"),
        ]),
    ]
    windows = [(0.0, 30.0), (28.0, 58.0)]
    out = _stitch(chunks, chunk_windows=windows, overlap_s=2.0)
    texts = [s.text for s in out.segments]
    # The overlap-region segment appears once, not twice.
    assert texts.count("in overlap region") == 1
    # Both surrounding segments survive intact.
    assert "preceding segment" in texts
    assert "after seam" in texts


def test_stitch_keeps_segments_outside_overlap_even_if_text_repeats():
    """Two chunks with the same backend-emitted text but at
    OBVIOUSLY different timestamps (well outside any overlap
    region) must both appear. The dedupe should only fire at
    seams, not for genuine repeat phrases later in the audio."""
    chunks = [
        TranscribeResult(segments=[Segment(5.0, 6.0, "uh huh")]),
        TranscribeResult(segments=[Segment(50.0, 51.0, "uh huh")]),
    ]
    windows = [(0.0, 30.0), (28.0, 58.0)]
    out = _stitch(chunks, chunk_windows=windows, overlap_s=2.0)
    # Two distinct timestamps survive — repeat phrase later in
    # the audio isn't dropped just because the text matches.
    assert len(out.segments) == 2
    starts = {s.start for s in out.segments}
    assert starts == {5.0, 50.0}


def test_stitch_carries_language_from_first_detection():
    chunks = [
        TranscribeResult(segments=[Segment(0, 1, "a")], language=None),
        TranscribeResult(segments=[Segment(28, 29, "b")], language="fr"),
    ]
    windows = [(0.0, 30.0), (28.0, 58.0)]
    out = _stitch(chunks, chunk_windows=windows, overlap_s=2.0)
    assert out.language == "fr"


def test_stitch_sets_duration_from_last_window():
    chunks = [
        TranscribeResult(segments=[Segment(0, 1, "a")]),
        TranscribeResult(segments=[Segment(28, 29, "b")]),
    ]
    windows = [(0.0, 30.0), (28.0, 58.0)]
    out = _stitch(chunks, chunk_windows=windows, overlap_s=2.0)
    assert out.duration == 58.0


# ---------------------------------------------------------------
# end-to-end transcribe_track with chunking
# ---------------------------------------------------------------


def _cfg(tmp_path: Path, **overrides: Any) -> SimpleNamespace:
    base = dict(
        profile="default",
        audio_chunk_seconds=30.0,
        audio_chunk_overlap_s=2.0,
        audio_output_dir=str(tmp_path / "audio"),
        media_backend_prefer="local",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_short_audio_makes_one_backend_call(tmp_path: Path):
    """A short file (under chunk_s) goes through as one
    backend call, no chunking, no offset."""
    wav = make_wav(tmp_path / "a.wav", duration_s=1.0)
    backend = StubAudioBackend(per_chunk_segments=1)
    transcribe_track(wav, cfg=_cfg(tmp_path), backend=backend)
    assert len(backend.transcribe_calls) == 1
    assert backend.transcribe_calls[0]["chunk_offset_s"] == 0.0


def test_long_audio_makes_one_call_per_chunk(tmp_path: Path):
    """A long file gets one backend call per chunk window.
    Use a very small chunk_s so we can synth a long-feeling
    audio without actually writing 90 seconds of WAV."""
    wav = make_wav(tmp_path / "a.wav", duration_s=2.0)
    # Force chunking via tiny chunk_s.
    cfg = _cfg(tmp_path, audio_chunk_seconds=0.5, audio_chunk_overlap_s=0.1)
    backend = StubAudioBackend(per_chunk_segments=1)
    transcribe_track(wav, cfg=cfg, backend=backend)
    # 2s file, 0.5s chunks with 0.1s overlap (step 0.4s):
    # boundaries (0, 0.5), (0.4, 0.9), (0.8, 1.3), (1.2, 1.7),
    # (1.6, 2.0). That's 5 chunks.
    assert len(backend.transcribe_calls) == 5
    # Offsets monotonically increase.
    offsets = [c["chunk_offset_s"] for c in backend.transcribe_calls]
    assert offsets == sorted(offsets)


def test_absolute_timestamps_after_stitching(tmp_path: Path):
    """The stub returns one segment at relative t=0.0 per
    chunk; after stitching, the segments should land at the
    chunks' absolute start times."""
    wav = make_wav(tmp_path / "a.wav", duration_s=2.0)
    cfg = _cfg(tmp_path, audio_chunk_seconds=0.5, audio_chunk_overlap_s=0.0)
    backend = StubAudioBackend(per_chunk_segments=1)
    result = transcribe_track(wav, cfg=cfg, backend=backend)
    starts = [s.start for s in result.segments]
    # No overlap → 4 contiguous chunks at 0.0 / 0.5 / 1.0 / 1.5.
    assert starts == [0.0, 0.5, 1.0, 1.5]


def test_progress_callback_fires_per_chunk(tmp_path: Path):
    wav = make_wav(tmp_path / "a.wav", duration_s=2.0)
    cfg = _cfg(tmp_path, audio_chunk_seconds=0.5, audio_chunk_overlap_s=0.0)
    backend = StubAudioBackend(per_chunk_segments=1)

    progress_log: list[tuple[int, int]] = []
    transcribe_track(
        wav, cfg=cfg, backend=backend,
        progress=lambda i, n: progress_log.append((i, n)),
    )
    # 4 chunks → progress fires (1,4), (2,4), (3,4), (4,4).
    assert progress_log == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_progress_callback_for_single_chunk(tmp_path: Path):
    """Short file → single-shot path → progress(1, 1) still
    fires so a UI can confirm completion."""
    wav = make_wav(tmp_path / "a.wav", duration_s=0.5)
    cfg = _cfg(tmp_path, audio_chunk_seconds=30.0)
    backend = StubAudioBackend(per_chunk_segments=1)

    progress_log: list[tuple[int, int]] = []
    transcribe_track(
        wav, cfg=cfg, backend=backend,
        progress=lambda i, n: progress_log.append((i, n)),
    )
    assert progress_log == [(1, 1)]
