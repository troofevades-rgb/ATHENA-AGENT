"""T4-01.1 — fixture sanity tests.

These confirm the synthesised fixtures have the properties later
test modules rely on: EXIF present-vs-absent, edited region
actually differs from original, large/small dimension bands.
"""

from __future__ import annotations

from PIL import Image

from tests.vision.fixtures import FIXTURES_DIR, ensure_fixtures


def test_all_six_fixtures_exist():
    out = ensure_fixtures()
    assert set(out.keys()) == {
        "original", "stripped", "edited",
        "recompressed", "large", "small",
    }
    for p in out.values():
        assert p.exists() and p.stat().st_size > 0


def test_original_has_exif_make_model_datetime():
    ensure_fixtures()
    ex = Image.open(FIXTURES_DIR / "original.jpg").getexif()
    assert ex.get(0x010F) == "AthenaCam"      # Make
    assert ex.get(0x0110) == "T4-01"          # Model
    assert ex.get(0x0132) == "2026:05:20 12:34:56"  # DateTime


def test_stripped_has_no_exif():
    ensure_fixtures()
    ex = Image.open(FIXTURES_DIR / "stripped.jpg").getexif()
    # Empty EXIF dict — no Make / Model / DateTime keys.
    assert 0x010F not in ex
    assert 0x0110 not in ex
    assert 0x0132 not in ex


def test_edited_differs_from_original_in_patch_region():
    ensure_fixtures()
    orig = Image.open(FIXTURES_DIR / "original.jpg").convert("RGB")
    edit = Image.open(FIXTURES_DIR / "edited.jpg").convert("RGB")
    # Sample the spliced patch — it's bright magenta in edited,
    # gradient sky in original.
    o_px = orig.getpixel((230, 230))
    e_px = edit.getpixel((230, 230))
    assert o_px != e_px
    # And the corners should be roughly equal (same gradient).
    assert orig.getpixel((10, 10))[0] - edit.getpixel((10, 10))[0] < 20


def test_size_bands():
    ensure_fixtures()
    large = Image.open(FIXTURES_DIR / "large.png")
    small = Image.open(FIXTURES_DIR / "small.png")
    assert max(large.size) >= 2000
    assert max(small.size) < 500


def test_recompressed_smaller_than_original():
    ensure_fixtures()
    o = (FIXTURES_DIR / "original.jpg").stat().st_size
    r = (FIXTURES_DIR / "recompressed.jpg").stat().st_size
    # quality=70 vs 92 always lands smaller for this content.
    assert r < o
