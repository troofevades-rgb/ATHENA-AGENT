"""T4-02.2 — pure-Python atom parser tests.

These run WITHOUT ffmpeg. Two consumer tests (the faststart
positive case + camera-original negative case) need the
fixtures, which are gitignored and built by conftest.py when
ffmpeg is available — they skip cleanly otherwise.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from athena.video.atoms import (
    Atom,
    faststart_remux_signature,
    is_likely_isobmff,
    parse_top_level_atoms,
)
from tests.video.fixtures import FIXTURES_DIR, have_ffmpeg


_NEED_FFMPEG = pytest.mark.skipif(
    not have_ffmpeg(),
    reason="ffmpeg not on PATH — fixtures not built",
)


# ---------------------------------------------------------------
# Parser shape (no fixtures needed for these)
# ---------------------------------------------------------------


def _craft_box(box_type: bytes, payload: bytes = b"") -> bytes:
    """Build a 32-bit-sized MP4 box header + payload bytes."""
    sz = 8 + len(payload)
    return struct.pack(">I", sz) + box_type + payload


def test_parse_finds_ftyp_moov_mdat(tmp_path: Path):
    """Craft a minimal file with three boxes and verify the
    parser sees them in order. Tests the 32-bit-size path."""
    blob = (
        _craft_box(b"ftyp", b"isom" + b"\x00" * 12)
        + _craft_box(b"moov", b"\x00" * 32)
        + _craft_box(b"mdat", b"\x00" * 64)
    )
    f = tmp_path / "tiny.mp4"
    f.write_bytes(blob)
    atoms = parse_top_level_atoms(f)
    assert [a.type for a in atoms] == ["ftyp", "moov", "mdat"]


def test_parse_handles_64bit_extended_size(tmp_path: Path):
    """A box with size=1 in the 32-bit field uses the following
    8 bytes as a 64-bit size. Parser must consume the right
    number of header bytes."""
    payload = b"\x00" * 32
    big_box = (
        struct.pack(">I", 1)            # 32-bit size = 1 → 64-bit follows
        + b"mdat"
        + struct.pack(">Q", 16 + len(payload))
        + payload
    )
    blob = _craft_box(b"ftyp", b"isom" + b"\x00" * 12) + big_box
    f = tmp_path / "ext.mp4"
    f.write_bytes(blob)
    atoms = parse_top_level_atoms(f)
    assert [a.type for a in atoms] == ["ftyp", "mdat"]
    # The mdat box's recorded size is the 64-bit value.
    assert atoms[1].size == 16 + len(payload)


def test_parse_handles_size_zero_last_box(tmp_path: Path):
    """size=0 means "extends to end of file" — the box claims
    the rest of the byte stream."""
    blob = (
        _craft_box(b"ftyp", b"isom" + b"\x00" * 12)
        + struct.pack(">I", 0) + b"mdat" + b"\x00" * 32
    )
    f = tmp_path / "z.mp4"
    f.write_bytes(blob)
    atoms = parse_top_level_atoms(f)
    assert [a.type for a in atoms] == ["ftyp", "mdat"]
    assert atoms[1].size == 8 + 32  # header + payload


def test_parse_stops_at_max_atoms(tmp_path: Path):
    """A malformed file with many tiny boxes shouldn't loop
    forever — max_atoms caps the walk."""
    box = _craft_box(b"free", b"\x00" * 4)  # 12-byte boxes
    f = tmp_path / "many.mp4"
    f.write_bytes(box * 100)
    atoms = parse_top_level_atoms(f, max_atoms=5)
    assert len(atoms) == 5


def test_parse_stops_on_malformed_size_smaller_than_header(tmp_path: Path):
    """A box that declares size < 8 (smaller than its own header)
    is malformed — the parser must not loop on it."""
    bad = struct.pack(">I", 4) + b"baad"  # size=4 < 8
    blob = _craft_box(b"ftyp", b"isom" + b"\x00" * 12) + bad
    f = tmp_path / "bad.mp4"
    f.write_bytes(blob)
    atoms = parse_top_level_atoms(f)
    # ftyp is fine; the bad atom is appended but the walk stops
    assert atoms[0].type == "ftyp"
    assert len(atoms) <= 2


def test_parse_empty_file_returns_empty(tmp_path: Path):
    f = tmp_path / "empty.mp4"
    f.write_bytes(b"")
    assert parse_top_level_atoms(f) == []


def test_parse_non_mp4_returns_short_or_empty(tmp_path: Path):
    """A JPEG file's first 8 bytes will parse as SOME garbage
    box type, but the walk should exit cleanly without raising.
    We don't require a specific output here — just that no
    exception leaks."""
    f = tmp_path / "fake.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    parse_top_level_atoms(f)  # must not raise


# ---------------------------------------------------------------
# is_likely_isobmff
# ---------------------------------------------------------------


def test_is_likely_isobmff_accepts_ftyp_start():
    assert is_likely_isobmff([Atom("ftyp", 32, 0), Atom("mdat", 100, 32)])


def test_is_likely_isobmff_accepts_moov_start():
    assert is_likely_isobmff([Atom("moov", 32, 0)])


def test_is_likely_isobmff_rejects_other_start():
    assert not is_likely_isobmff([Atom("ID3 ", 32, 0)])
    assert not is_likely_isobmff([])


# ---------------------------------------------------------------
# faststart_remux_signature
# ---------------------------------------------------------------


def test_faststart_positive_synthetic():
    """moov before mdat → moov_before_mdat=True + the documented
    remux interpretation string."""
    atoms = [
        Atom("ftyp", 32, 0),
        Atom("moov", 1000, 32),
        Atom("free", 8, 1032),
        Atom("mdat", 8000, 1040),
    ]
    sig = faststart_remux_signature(atoms)
    assert sig["moov_before_mdat"] is True
    assert sig["moov_index"] < sig["mdat_index"]
    assert "qt-faststart" in sig["interpretation"]


def test_faststart_negative_synthetic():
    """mdat before moov → moov_before_mdat=False + the
    camera-original interpretation string."""
    atoms = [
        Atom("ftyp", 32, 0),
        Atom("free", 8, 32),
        Atom("mdat", 8000, 40),
        Atom("moov", 1000, 8040),
    ]
    sig = faststart_remux_signature(atoms)
    assert sig["moov_before_mdat"] is False
    assert sig["mdat_index"] < sig["moov_index"]
    assert "camera capture" in sig["interpretation"]


def test_faststart_missing_moov_reported():
    atoms = [Atom("ftyp", 32, 0), Atom("mdat", 800, 32)]
    sig = faststart_remux_signature(atoms)
    assert sig["moov_index"] == -1
    assert "moov atom missing" in sig["interpretation"]


def test_faststart_missing_mdat_reported():
    atoms = [Atom("ftyp", 32, 0), Atom("moov", 800, 32)]
    sig = faststart_remux_signature(atoms)
    assert sig["mdat_index"] == -1
    assert "mdat atom missing" in sig["interpretation"]


def test_faststart_neither_atom_present():
    atoms = [Atom("ftyp", 32, 0), Atom("free", 100, 32)]
    sig = faststart_remux_signature(atoms)
    assert sig["moov_before_mdat"] is False
    assert "probably not MP4" in sig["interpretation"]


# ---------------------------------------------------------------
# Real fixtures — skip-if-ffmpeg-absent
# ---------------------------------------------------------------


@_NEED_FFMPEG
def test_faststart_signature_on_real_faststart_fixture():
    atoms = parse_top_level_atoms(FIXTURES_DIR / "faststart.mp4")
    sig = faststart_remux_signature(atoms)
    assert sig["moov_before_mdat"] is True


@_NEED_FFMPEG
def test_faststart_signature_on_real_camera_original_fixture():
    atoms = parse_top_level_atoms(FIXTURES_DIR / "camera_original.mp4")
    sig = faststart_remux_signature(atoms)
    assert sig["moov_before_mdat"] is False
