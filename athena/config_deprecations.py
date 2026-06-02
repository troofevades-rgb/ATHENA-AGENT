"""Configuration deprecation registry — legacy field map + dedup state.

Extracted from ``athena/config.py`` 2026-06-01 as part of the
consolidation pass (see ``MEMORY.md → project-consolidation-pass``).
The deprecation surface is orthogonal to the Config dataclass
itself: a translation table between legacy flat-field names and
their new nested homes, plus a per-process dedup set so a startup
that calls ``load_config()`` twice doesn't double-warn.

Public surface (importable from ``athena.config`` for back-compat):

  :data:`LEGACY_FIELD_MAP` -- ``{legacy_key: (nested_section, attr)}``
  :func:`emit_deprecation`     -- log once per (path, key) pair
  :func:`reset_deprecation_dedup` -- test helper; clear the dedup set
  :func:`reported_deprecations`   -- public read of the dedup set

The names with a leading underscore (``_LEGACY_FIELD_MAP``,
``_DEPRECATION_WARNED``, ``_emit_deprecation``) remain importable
from ``athena.config`` as backwards-compat aliases for one
release; new code should use the public names from this module.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Map legacy flat-field name -> (nested_dataclass_field, attribute_on_nested).
# Add new entries here as subsystems migrate. ``Config.__getattr__`` /
# ``__setattr__`` shims walk this table to translate legacy access at
# runtime, and ``load_config()`` folds the values from the TOML on-disk
# format into their new nested homes.
LEGACY_FIELD_MAP: dict[str, tuple[str, str]] = {
    "skills_autoload": ("skills", "autoload"),
    "skills_autoload_interval": ("skills", "autoload_interval"),
    "bash_allowlist": ("bash", "allowlist"),
    "bash_extra_denylist": ("bash", "extra_denylist"),
    "computer_use_enabled": ("computer", "use_enabled"),
    "computer_permission_mode": ("computer", "permission_mode"),
    "computer_app_allowlist": ("computer", "app_allowlist"),
    "computer_app_denylist": ("computer", "app_denylist"),
    "computer_kill_hotkey": ("computer", "kill_hotkey"),
    "computer_max_actions_per_task": ("computer", "max_actions_per_task"),
    "computer_max_actions_per_sec": ("computer", "max_actions_per_sec"),
    "computer_backend": ("computer", "backend"),
    "computer_dry_run": ("computer", "dry_run"),
    "computer_audit_path": ("computer", "audit_path"),
    "computer_screenshots_dir": ("computer", "screenshots_dir"),
    "computer_deny_during_goal_loop": ("computer", "deny_during_goal_loop"),
    # R4 stage 5 -- OCR
    "ocr_enabled": ("ocr", "enabled"),
    "ocr_backend_prefer": ("ocr", "backend_prefer"),
    "ocr_languages": ("ocr", "languages"),
    "ocr_min_confidence": ("ocr", "min_confidence"),
    "ocr_tesseract_cmd": ("ocr", "tesseract_cmd"),
    # R4 stage 5 -- Video generation broker
    "video_generation_enabled": ("video_generation", "enabled"),
    "video_backend_prefer": ("video_generation", "backend_prefer"),
    "video_confirm_over_seconds": ("video_generation", "confirm_over_seconds"),
    "video_confirm_over_cost": ("video_generation", "confirm_over_cost"),
    "video_output_dir": ("video_generation", "output_dir"),
    "video_poll_interval_s": ("video_generation", "poll_interval_s"),
    "video_backend": ("video_generation", "backend"),
    # R4 stage 5 -- Video analysis
    "video_enabled": ("video_analysis", "enabled"),
    "video_ffmpeg_path": ("video_analysis", "ffmpeg_path"),
    "video_ffprobe_path": ("video_analysis", "ffprobe_path"),
    "video_frames_dir": ("video_analysis", "frames_dir"),
    "video_max_frames": ("video_analysis", "max_frames"),
    "video_default_extract": ("video_analysis", "default_extract"),
    "video_sampled_interval_s": ("video_analysis", "sampled_interval_s"),
}


# Per-process dedup state. Each ``(config_path, legacy_key)`` pair
# emits its warning ONCE per process. Motivation: ``__main__.py`` calls
# ``load_config()`` twice during startup (``startup_notice`` +
# the real cfg), which made every deprecation surface twice. The set
# is also a read source for the ``athena doctor`` summary so the
# operator sees a one-stop report without re-reading the config.
DEPRECATION_WARNED: set[tuple[str, str]] = set()


def reset_deprecation_dedup() -> None:
    """Clear the in-process dedup state. Called from tests so
    deprecation pins are hermetic regardless of the order test files
    run in (each test gets a clean slate to assert warning emission)."""
    DEPRECATION_WARNED.clear()


def reported_deprecations() -> frozenset[tuple[str, str]]:
    """Public read of the dedup state: returns the set of
    ``(config_path, legacy_key)`` pairs that have warned this process.
    Callers (e.g. ``athena doctor``) can surface a one-stop summary
    without re-reading the config file."""
    return frozenset(DEPRECATION_WARNED)


def emit_deprecation(config_path: Path, legacy_key: str, message: str) -> None:
    """Emit ``message`` to stderr the FIRST time the
    ``(config_path, legacy_key)`` pair is reported in this process.
    Subsequent calls are silent."""
    key = (str(config_path), legacy_key)
    if key in DEPRECATION_WARNED:
        return
    DEPRECATION_WARNED.add(key)
    print(message, file=sys.stderr)


# Backwards-compatible private-name aliases. Existing callers that
# import the underscore-prefixed names from ``athena.config`` keep
# working for one release. The aliases are also re-exported from
# ``athena.config`` (the import in config.py preserves the public
# surface there).
_LEGACY_FIELD_MAP = LEGACY_FIELD_MAP
_DEPRECATION_WARNED = DEPRECATION_WARNED
_emit_deprecation = emit_deprecation


__all__ = (
    "LEGACY_FIELD_MAP",
    "DEPRECATION_WARNED",
    "emit_deprecation",
    "reset_deprecation_dedup",
    "reported_deprecations",
    # Back-compat aliases
    "_LEGACY_FIELD_MAP",
    "_DEPRECATION_WARNED",
    "_emit_deprecation",
)
