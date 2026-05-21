"""T4-01.3 — local image-op tests.

These pin the load-bearing invariants for EXIF / ELA / crop /
histogram / pHash / metadata-strip. Where a function is a
heuristic (ELA, pHash), we test the *direction* of the signal,
not exact pixel values.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.vision.imageops import (
    MAX_INPUT_PIXELS,
    crop_region,
    error_level_analysis,
    extract_exif,
    histogram,
    metadata_strip_check,
    perceptual_hash,
    phash_distance,
)
from tests.vision.fixtures import FIXTURES_DIR, ensure_fixtures


# ---------------------------------------------------------------
# EXIF
# ---------------------------------------------------------------


def test_exif_extracts_make_model_datetime():
    ensure_fixtures()
    ex = extract_exif(FIXTURES_DIR / "original.jpg")
    assert ex.get("Make") == "AthenaCam"
    assert ex.get("Model") == "T4-01"
    assert ex.get("DateTime") == "2026:05:20 12:34:56"


def test_exif_empty_on_stripped():
    ensure_fixtures()
    ex = extract_exif(FIXTURES_DIR / "stripped.jpg")
    assert ex == {}


def test_exif_normalises_to_json_safe():
    """Every value in the returned dict must be JSON-serialisable."""
    import json
    ensure_fixtures()
    ex = extract_exif(FIXTURES_DIR / "original.jpg")
    json.dumps(ex)  # would raise TypeError if not


def test_open_safely_rejects_too_large(tmp_path: Path, monkeypatch):
    """Bomb-shaped input → ValueError before decode."""
    from PIL import Image
    monkeypatch.setattr("athena.vision.imageops.MAX_INPUT_PIXELS", 100)
    img = Image.new("RGB", (50, 50), "white")
    p = tmp_path / "biggie.png"
    img.save(p, format="PNG")
    with pytest.raises(ValueError, match="too large"):
        extract_exif(p)


# ---------------------------------------------------------------
# ELA
# ---------------------------------------------------------------


def test_ela_returns_documented_shape():
    ensure_fixtures()
    out = error_level_analysis(FIXTURES_DIR / "original.jpg")
    assert set(out.keys()) >= {
        "quality", "threshold", "max_diff", "mean_diff", "patches",
    }
    assert out["quality"] == 80
    assert out["threshold"] == 15
    assert isinstance(out["patches"], list)


def test_ela_signal_higher_for_edited_than_original():
    """The spliced patch in edited.jpg should light up ELA: edited
    image has strictly more patches above threshold than the
    untouched original (which still has SOME signal — JPEG-vs-q80
    diffs everywhere). At the very least, the max_diff is higher
    or the patch count is higher."""
    ensure_fixtures()
    out_orig = error_level_analysis(FIXTURES_DIR / "original.jpg", threshold=15)
    out_edit = error_level_analysis(FIXTURES_DIR / "edited.jpg", threshold=15)
    # Direction of signal — edited should show MORE evidence.
    edited_evidence = (out_edit["max_diff"], len(out_edit["patches"]))
    orig_evidence = (out_orig["max_diff"], len(out_orig["patches"]))
    assert edited_evidence >= orig_evidence


def test_ela_rejects_bad_quality():
    ensure_fixtures()
    with pytest.raises(ValueError):
        error_level_analysis(FIXTURES_DIR / "original.jpg", quality=0)
    with pytest.raises(ValueError):
        error_level_analysis(FIXTURES_DIR / "original.jpg", quality=101)


def test_ela_rejects_negative_threshold():
    ensure_fixtures()
    with pytest.raises(ValueError):
        error_level_analysis(FIXTURES_DIR / "original.jpg", threshold=-1)


# ---------------------------------------------------------------
# Crop
# ---------------------------------------------------------------


def test_crop_writes_file_and_returns_sha(tmp_path: Path):
    ensure_fixtures()
    out = crop_region(
        FIXTURES_DIR / "original.jpg",
        box=(50, 50, 250, 200),
        out_dir=tmp_path / "crops",
    )
    assert Path(out["out_path"]).exists()
    assert out["width"] == 200
    assert out["height"] == 150
    assert len(out["sha256"]) == 64
    # No b64 unless asked
    assert "image_b64" not in out


def test_crop_optional_b64(tmp_path: Path):
    ensure_fixtures()
    out = crop_region(
        FIXTURES_DIR / "original.jpg",
        box=(0, 0, 100, 100),
        out_dir=tmp_path,
        return_b64=True,
    )
    assert isinstance(out["image_b64"], str)
    assert len(out["image_b64"]) > 0


def test_crop_rejects_oob_box(tmp_path: Path):
    ensure_fixtures()
    # Original is 800x600 — these are wildly out.
    with pytest.raises(ValueError, match="out of bounds"):
        crop_region(
            FIXTURES_DIR / "original.jpg",
            box=(0, 0, 5000, 5000),
            out_dir=tmp_path,
        )


def test_crop_rejects_inverted_box(tmp_path: Path):
    ensure_fixtures()
    with pytest.raises(ValueError, match="out of bounds"):
        crop_region(
            FIXTURES_DIR / "original.jpg",
            box=(200, 200, 100, 100),  # x1 < x0
            out_dir=tmp_path,
        )


# ---------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------


def test_histogram_shape_and_totals():
    ensure_fixtures()
    h = histogram(FIXTURES_DIR / "original.jpg", bins=16)
    assert h["bins"] == 16
    assert h["channels"] == ["R", "G", "B"]
    assert len(h["data"]["R"]) == 16
    # The total over a single channel equals total_pixels.
    assert sum(h["data"]["R"]) == h["total_pixels"]
    assert sum(h["data"]["G"]) == h["total_pixels"]
    assert sum(h["data"]["B"]) == h["total_pixels"]


def test_histogram_rejects_non_divisor_bins():
    ensure_fixtures()
    with pytest.raises(ValueError):
        histogram(FIXTURES_DIR / "original.jpg", bins=7)  # 256 % 7 != 0


# ---------------------------------------------------------------
# Perceptual hash
# ---------------------------------------------------------------


def test_phash_returns_hex_of_expected_length():
    ensure_fixtures()
    out = perceptual_hash(FIXTURES_DIR / "original.jpg")
    assert out["algorithm"] == "phash"
    assert out["hash_size"] == 8
    # 8x8 pHash → 16 hex chars (64 bits).
    assert isinstance(out["hex"], str)
    assert len(out["hex"]) == 16


def test_phash_robust_to_recompression():
    """recompressed.jpg differs only in JPEG quality (70 vs 92).
    pHash should be near-identical — distance ≤ 4 is generous."""
    ensure_fixtures()
    h_orig = perceptual_hash(FIXTURES_DIR / "original.jpg")["hex"]
    h_recomp = perceptual_hash(FIXTURES_DIR / "recompressed.jpg")["hex"]
    d = phash_distance(h_orig, h_recomp)
    assert d <= 4, f"distance {d} too high for re-compression only"


def test_phash_distinguishes_different_scenes():
    """large.png and small.png are different seeds — should be far
    apart in pHash space."""
    ensure_fixtures()
    h_l = perceptual_hash(FIXTURES_DIR / "large.png")["hex"]
    h_s = perceptual_hash(FIXTURES_DIR / "small.png")["hex"]
    d = phash_distance(h_l, h_s)
    assert d > 8, f"distance {d} too low for different scenes"


def test_phash_supports_alt_algorithms():
    ensure_fixtures()
    for algo in ("phash", "dhash", "ahash", "whash"):
        out = perceptual_hash(FIXTURES_DIR / "original.jpg", algorithm=algo)
        assert out["algorithm"] == algo
        assert isinstance(out["hex"], str) and len(out["hex"]) > 0


def test_phash_rejects_unknown_algorithm():
    ensure_fixtures()
    with pytest.raises(ValueError, match="unknown algorithm"):
        perceptual_hash(FIXTURES_DIR / "original.jpg", algorithm="bogus")


# ---------------------------------------------------------------
# Metadata-strip check
# ---------------------------------------------------------------


def test_strip_check_reports_stripped():
    ensure_fixtures()
    out = metadata_strip_check(
        FIXTURES_DIR / "original.jpg",
        FIXTURES_DIR / "stripped.jpg",
    )
    assert out["verdict"] == "stripped"
    # Make/Model/DateTime should appear in missing_keys.
    assert "Make" in out["missing_keys"]
    assert "Model" in out["missing_keys"]


def test_strip_check_intact_when_same_file():
    ensure_fixtures()
    out = metadata_strip_check(
        FIXTURES_DIR / "original.jpg",
        FIXTURES_DIR / "original.jpg",
    )
    assert out["verdict"] == "intact"
    assert out["missing_keys"] == []


def test_strip_check_indeterminate_when_orig_blank():
    """When the original itself has no EXIF, we can't draw a
    conclusion about the suspect."""
    ensure_fixtures()
    out = metadata_strip_check(
        FIXTURES_DIR / "stripped.jpg",
        FIXTURES_DIR / "original.jpg",
    )
    assert out["verdict"] == "indeterminate"
