"""Public-surface tests for athena/config_deprecations.py.

The module was extracted from athena/config.py in the 2026-06-01
consolidation pass. This file pins:

  1. New public names (LEGACY_FIELD_MAP, emit_deprecation,
     reset_deprecation_dedup, reported_deprecations) importable
     from athena.config_deprecations.
  2. Backwards-compatible underscore aliases still importable
     from athena.config for one release.
  3. Public and legacy names are the SAME objects (state shared
     across both surfaces, so a reset via one is visible via
     the other).
"""

from __future__ import annotations


def test_public_names_importable() -> None:
    from athena.config_deprecations import (
        DEPRECATION_WARNED,
        LEGACY_FIELD_MAP,
        emit_deprecation,
        reported_deprecations,
        reset_deprecation_dedup,
    )

    assert isinstance(LEGACY_FIELD_MAP, dict)
    assert isinstance(DEPRECATION_WARNED, set)
    assert callable(emit_deprecation)
    assert callable(reset_deprecation_dedup)
    assert callable(reported_deprecations)


def test_legacy_underscore_aliases_importable_from_config() -> None:
    """Existing callers that import from ``athena.config`` keep
    working: every underscore-prefixed name still resolves."""
    from athena.config import (
        _DEPRECATION_WARNED,
        _LEGACY_FIELD_MAP,
        _emit_deprecation,
        reported_deprecations,
        reset_deprecation_dedup,
    )

    assert _LEGACY_FIELD_MAP is not None
    assert _DEPRECATION_WARNED is not None
    assert callable(_emit_deprecation)
    assert callable(reset_deprecation_dedup)
    assert callable(reported_deprecations)


def test_legacy_and_public_names_share_state() -> None:
    """The aliases point at the SAME objects -- a reset via the
    public name is observable via the legacy name (and vice
    versa). Without this, the two import paths would behave like
    independent registries and tests would silently miss
    dedup-state regressions."""
    from athena.config import _DEPRECATION_WARNED, _LEGACY_FIELD_MAP, _emit_deprecation
    from athena.config_deprecations import (
        DEPRECATION_WARNED,
        LEGACY_FIELD_MAP,
        emit_deprecation,
    )

    assert _LEGACY_FIELD_MAP is LEGACY_FIELD_MAP
    assert _DEPRECATION_WARNED is DEPRECATION_WARNED
    assert _emit_deprecation is emit_deprecation


def test_reset_visible_through_both_surfaces() -> None:
    """Adding to the dedup set via one entry point and resetting via
    the other must propagate."""
    from pathlib import Path

    from athena.config import _DEPRECATION_WARNED, _emit_deprecation
    from athena.config_deprecations import (
        DEPRECATION_WARNED,
        reset_deprecation_dedup,
    )

    reset_deprecation_dedup()
    assert len(DEPRECATION_WARNED) == 0

    # Emit via the legacy name -- should show up via the public set.
    test_path = Path("/test")
    _emit_deprecation(test_path, "some_legacy_key", "warning: test")
    assert len(_DEPRECATION_WARNED) == 1
    assert len(DEPRECATION_WARNED) == 1
    # Key uses str(path) which is platform-specific (POSIX vs
    # Windows separator); pin via the same conversion the emitter
    # uses.
    assert (str(test_path), "some_legacy_key") in DEPRECATION_WARNED

    # Reset via the public function -- legacy view also clears.
    reset_deprecation_dedup()
    assert len(_DEPRECATION_WARNED) == 0
    assert len(DEPRECATION_WARNED) == 0


def test_legacy_field_map_has_expected_size() -> None:
    """Sanity: the table should have substantially more than zero
    entries. Catches accidental clobbering of the dict on a future
    refactor."""
    from athena.config_deprecations import LEGACY_FIELD_MAP

    # 30+ entries today (skills_*, bash_*, computer_*, ocr_*,
    # video_generation_*, video_analysis_*). Pin a floor.
    assert len(LEGACY_FIELD_MAP) >= 30

    # Spot-check a few representative entries to catch silent
    # restructuring (a renamed dict that still has length but
    # different content).
    assert LEGACY_FIELD_MAP["bash_allowlist"] == ("bash", "allowlist")
    assert LEGACY_FIELD_MAP["computer_use_enabled"] == (
        "computer",
        "use_enabled",
    )
    assert LEGACY_FIELD_MAP["video_backend"] == (
        "video_generation",
        "backend",
    )
