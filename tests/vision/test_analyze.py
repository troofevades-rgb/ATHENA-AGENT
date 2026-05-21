"""T4-01.5 — vision_analyze tool tests.

Every mode is exercised end-to-end through ``_run`` with a
synthetic cfg + (for describe) an injected stub provider so we
don't rely on a real multimodal model. The tool layer above
just calls ``_run`` — testing here is equivalent to testing
through @tool dispatch.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.vision import analyze
from athena.vision.analyze import VALID_MODES, _run
from tests.vision.fixtures import FIXTURES_DIR, ensure_fixtures


# ---------------------------------------------------------------
# stub plumbing
# ---------------------------------------------------------------


def _cfg(tmp_path: Path, **overrides: Any) -> SimpleNamespace:
    """A synthetic cfg with the load-bearing vision fields."""
    base = dict(
        profile="default",
        vision_enabled=True,
        vision_max_input_pixels=80_000_000,
        vision_ela_quality=80,
        vision_ela_threshold=15,
        vision_phash_algorithm="phash",
        vision_phash_size=8,
        vision_long_edge_cap=None,
        vision_crop_dir=str(tmp_path / "crops"),
        provider="ollama",
        model="stub-vision-model",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _route_profile_dir(tmp_path: Path, monkeypatch):
    """Redirect athena.config.profile_dir so the hash-log lands in tmp_path."""
    monkeypatch.setattr(
        "athena.vision.analyze.profile_dir",
        lambda profile="default": tmp_path,
    )
    yield


class _StubProvider:
    def __init__(self, *, response="A cat on a windowsill."):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def describe(self, messages):
        self.calls.append({"messages": messages})
        return self.response


# ---------------------------------------------------------------
# mode=exif
# ---------------------------------------------------------------


def test_exif_mode_returns_camera_fields(tmp_path: Path):
    ensure_fixtures()
    out = json.loads(_run(
        mode="exif",
        path=str(FIXTURES_DIR / "original.jpg"),
        _cfg=_cfg(tmp_path),
    ))
    assert out["mode"] == "exif"
    assert out["exif"]["Make"] == "AthenaCam"
    assert out["exif"]["DateTime"].startswith("2026:")
    assert len(out["sha256"]) == 64


def test_exif_mode_logs_audit_row(tmp_path: Path):
    ensure_fixtures()
    _run(
        mode="exif",
        path=str(FIXTURES_DIR / "original.jpg"),
        _cfg=_cfg(tmp_path),
    )
    audit = tmp_path / "vision_audit.jsonl"
    rows = [json.loads(l) for l in audit.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["mode"] == "exif"


# ---------------------------------------------------------------
# mode=ela
# ---------------------------------------------------------------


def test_ela_mode_returns_patches(tmp_path: Path):
    ensure_fixtures()
    out = json.loads(_run(
        mode="ela",
        path=str(FIXTURES_DIR / "edited.jpg"),
        _cfg=_cfg(tmp_path),
    ))
    assert out["mode"] == "ela"
    assert "patches" in out
    assert out["quality"] == 80


def test_ela_mode_honours_overrides(tmp_path: Path):
    ensure_fixtures()
    out = json.loads(_run(
        mode="ela",
        path=str(FIXTURES_DIR / "original.jpg"),
        quality=50, threshold=5,
        _cfg=_cfg(tmp_path),
    ))
    assert out["quality"] == 50
    assert out["threshold"] == 5


# ---------------------------------------------------------------
# mode=crop
# ---------------------------------------------------------------


def test_crop_mode_writes_artifact(tmp_path: Path):
    ensure_fixtures()
    out = json.loads(_run(
        mode="crop",
        path=str(FIXTURES_DIR / "original.jpg"),
        box=[10, 10, 110, 110],
        _cfg=_cfg(tmp_path),
    ))
    assert out["mode"] == "crop"
    assert Path(out["out_path"]).exists()
    assert out["width"] == 100
    assert out["height"] == 100


def test_crop_missing_box_returns_error(tmp_path: Path):
    ensure_fixtures()
    out = json.loads(_run(
        mode="crop",
        path=str(FIXTURES_DIR / "original.jpg"),
        _cfg=_cfg(tmp_path),
    ))
    assert "error" in out
    assert "box" in out["error"]


# ---------------------------------------------------------------
# mode=histogram
# ---------------------------------------------------------------


def test_histogram_mode_returns_bins(tmp_path: Path):
    ensure_fixtures()
    out = json.loads(_run(
        mode="histogram",
        path=str(FIXTURES_DIR / "original.jpg"),
        bins=8,
        _cfg=_cfg(tmp_path),
    ))
    assert out["mode"] == "histogram"
    assert out["bins"] == 8
    assert len(out["data"]["R"]) == 8


# ---------------------------------------------------------------
# mode=phash
# ---------------------------------------------------------------


def test_phash_mode_returns_hex(tmp_path: Path):
    ensure_fixtures()
    out = json.loads(_run(
        mode="phash",
        path=str(FIXTURES_DIR / "original.jpg"),
        _cfg=_cfg(tmp_path),
    ))
    assert out["mode"] == "phash"
    assert out["algorithm"] == "phash"
    assert len(out["hex"]) == 16


# ---------------------------------------------------------------
# mode=compare
# ---------------------------------------------------------------


def test_compare_mode_detects_stripped(tmp_path: Path):
    ensure_fixtures()
    out = json.loads(_run(
        mode="compare",
        paths=[
            str(FIXTURES_DIR / "original.jpg"),
            str(FIXTURES_DIR / "stripped.jpg"),
        ],
        _cfg=_cfg(tmp_path),
    ))
    assert out["mode"] == "compare"
    assert out["metadata_strip_check"]["verdict"] == "stripped"
    assert "Make" in out["metadata_strip_check"]["missing_keys"]
    assert out["phash_distance"] <= 8


def test_compare_mode_requires_two_paths(tmp_path: Path):
    out = json.loads(_run(
        mode="compare",
        paths=["just-one.jpg"],
        _cfg=_cfg(tmp_path),
    ))
    assert "error" in out


def test_compare_mode_strong_match_label(tmp_path: Path):
    ensure_fixtures()
    out = json.loads(_run(
        mode="compare",
        paths=[
            str(FIXTURES_DIR / "original.jpg"),
            str(FIXTURES_DIR / "recompressed.jpg"),
        ],
        _cfg=_cfg(tmp_path),
    ))
    # "identical" or "strong-match" — both fine.
    assert out["phash_distance_reading"] in (
        "identical", "strong-match (mild transform)",
    )


# ---------------------------------------------------------------
# mode=describe (stub provider)
# ---------------------------------------------------------------


def test_describe_passes_text_and_image_to_provider(tmp_path: Path):
    ensure_fixtures()
    stub = _StubProvider(response="It is a synthetic photo of trees.")
    out = json.loads(_run(
        mode="describe",
        path=str(FIXTURES_DIR / "original.jpg"),
        prompt="What's in this image?",
        _cfg=_cfg(tmp_path),
        _provider_factory=lambda cfg: stub,
    ))
    assert out["mode"] == "describe"
    assert out["answer"] == "It is a synthetic photo of trees."
    assert out["tiled"] is False
    assert out["tiles"] == 1
    # The provider got one user message; first content block is
    # the prompt text, the second is the image block.
    assert len(stub.calls) == 1
    user = stub.calls[0]["messages"][0]
    assert user["role"] == "user"
    parts = user["content"]
    assert parts[0]["type"] == "text"
    assert parts[0]["text"] == "What's in this image?"
    # second part is an image block (ollama shape default)
    assert parts[1]["type"] == "image"


def test_describe_tiles_large_image(tmp_path: Path):
    ensure_fixtures()
    stub = _StubProvider(response="A landscape with trees.")
    out = json.loads(_run(
        mode="describe",
        path=str(FIXTURES_DIR / "large.png"),
        _cfg=_cfg(tmp_path),
        _provider_factory=lambda cfg: stub,
    ))
    assert out["tiled"] is True
    assert out["tiles"] > 1


def test_describe_no_provider_returns_clear_error(tmp_path: Path):
    ensure_fixtures()
    out = json.loads(_run(
        mode="describe",
        path=str(FIXTURES_DIR / "original.jpg"),
        _cfg=_cfg(tmp_path),
        _provider_factory=lambda cfg: None,
    ))
    assert "error" in out
    assert "no vision-capable provider" in out["error"]


def test_describe_provider_exception_surfaces_as_error(tmp_path: Path):
    ensure_fixtures()
    class _Boom:
        def describe(self, _):
            raise RuntimeError("model offline")
    out = json.loads(_run(
        mode="describe",
        path=str(FIXTURES_DIR / "original.jpg"),
        _cfg=_cfg(tmp_path),
        _provider_factory=lambda cfg: _Boom(),
    ))
    assert "error" in out
    assert "model offline" in out["error"]


# ---------------------------------------------------------------
# gate checks
# ---------------------------------------------------------------


def test_vision_disabled_short_circuits(tmp_path: Path):
    ensure_fixtures()
    out = json.loads(_run(
        mode="exif",
        path=str(FIXTURES_DIR / "original.jpg"),
        _cfg=_cfg(tmp_path, vision_enabled=False),
    ))
    assert "error" in out
    assert "vision_enabled=False" in out["error"]
    # And NO audit row was written when gate refuses.
    audit = tmp_path / "vision_audit.jsonl"
    assert not audit.exists()


def test_unknown_mode_rejected(tmp_path: Path):
    out = json.loads(_run(
        mode="rotate",  # not in VALID_MODES
        path="foo.jpg",
        _cfg=_cfg(tmp_path),
    ))
    assert "error" in out
    assert "unknown mode" in out["error"]


def test_missing_file_returns_error(tmp_path: Path):
    out = json.loads(_run(
        mode="exif",
        path=str(tmp_path / "nope.jpg"),
        _cfg=_cfg(tmp_path),
    ))
    assert "error" in out
    assert "file not found" in out["error"]


# ---------------------------------------------------------------
# tool registration
# ---------------------------------------------------------------


def test_tool_registered_under_vision_toolset():
    import athena.tools  # noqa: F401 — register all tools
    from athena.tools.registry import all_tools
    names = {t.name for t in all_tools()}
    assert "vision_analyze" in names
    # And under the vision toolset
    by_name = {t.name: t for t in all_tools()}
    assert by_name["vision_analyze"].toolset == "vision"


def test_tool_describes_all_seven_modes():
    """The model parses these out of the schema — every mode
    must appear in the enum."""
    import athena.tools  # noqa: F401
    from athena.tools.registry import get_tool
    t = get_tool("vision_analyze")
    enum = t.parameters["properties"]["mode"]["enum"]
    assert set(enum) == set(VALID_MODES)
    assert "describe" in enum and "compare" in enum
