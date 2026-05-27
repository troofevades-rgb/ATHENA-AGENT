"""Unit tests for ``athena.tui_gateway.banner_data.build_banner``.

The function snapshots three pieces of state for the TUI:
  - theme palette (resolved from cfg.theme via athena.ui.THEMES)
  - owl art (loaded from athena/_owl_art.txt)
  - tool catalog (grouped by toolset, capped at 8 visible)

These tests exercise each branch without spawning the actual
Ink subprocess — that's covered by ``test_subprocess.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.config import Config
from athena.tui_gateway.banner_data import (
    _MAX_TOOLS_PER_SET,
    _MAX_VISIBLE_TOOLSETS,
    build_banner,
)
from athena.tui_gateway.events import ToolSetSummary


def test_build_banner_carries_model_and_cwd():
    cfg = Config()
    banner = build_banner(
        model="qwen-test", cwd=Path("/tmp/ws"), cfg=cfg
    )
    assert banner.model == "qwen-test"
    assert banner.cwd == str(Path("/tmp/ws"))
    assert banner.type == "banner"


def test_build_banner_resolves_theme_palette():
    cfg = Config()
    banner = build_banner(
        model="m", cwd=Path("/tmp"), cfg=cfg, theme_name="noctua"
    )
    assert banner.theme == "noctua"
    assert banner.palette is not None
    assert banner.palette.name == "noctua"
    # Noctua's primary is the electric cyan.
    assert banner.palette.primary == "#43e8ff"
    assert len(banner.palette.gradient) >= 4


def test_build_banner_falls_back_on_unknown_theme():
    """A typo in cfg.theme must NOT crash session start. The
    fallback is phosphor (the documented default)."""
    cfg = Config()
    banner = build_banner(
        model="m", cwd=Path("/tmp"), cfg=cfg, theme_name="not-a-real-theme"
    )
    assert banner.palette is not None
    assert banner.palette.name == "phosphor"


def test_build_banner_carries_owl_art():
    cfg = Config()
    banner = build_banner(model="m", cwd=Path("/tmp"), cfg=cfg)
    # The bundled art has at least 50 rows per
    # ``tests/test_ui_banner.py::test_owl_large_present``.
    assert len(banner.owl_art) >= 50
    # All rows ljust-padded to equal width.
    assert len({len(r) for r in banner.owl_art}) == 1


def test_build_banner_owl_art_empty_when_file_missing(monkeypatch):
    """Missing owl_art.txt must NOT crash banner build."""
    cfg = Config()
    monkeypatch.setattr(
        "athena.tui_gateway.banner_data._load_owl_art",
        lambda: [],
    )
    banner = build_banner(model="m", cwd=Path("/tmp"), cfg=cfg)
    assert banner.owl_art == []


def test_build_banner_tools_catalog_structure():
    cfg = Config()
    banner = build_banner(model="m", cwd=Path("/tmp"), cfg=cfg)
    # Tools should be ToolSetSummary instances, ordered with
    # priority toolsets first.
    assert all(isinstance(t, ToolSetSummary) for t in banner.tools)
    # Capped at MAX_VISIBLE + 1 (the synthesized "…" overflow row).
    assert len(banner.tools) <= _MAX_VISIBLE_TOOLSETS + 1


def test_build_banner_overflow_row_uses_ellipsis_name(monkeypatch):
    """When there are more toolsets than fit, the final entry has
    name="…" and hidden_count > 0 — the TUI relies on that
    sentinel to render the "+N more toolsets" line specially."""
    # Force a registry with many toolsets to trigger overflow.
    from athena.tools.registry import Tool

    fake_groups: dict[str, list[Tool]] = {}
    for i in range(_MAX_VISIBLE_TOOLSETS + 3):
        fake_groups[f"set{i}"] = []

    def fake_all_tools():
        out = []
        for ts, _ in fake_groups.items():
            out.append(
                type("T", (), {"toolset": ts, "name": f"tool_{ts}"})()
            )
        return out

    monkeypatch.setattr(
        "athena.tools.registry.all_tools", fake_all_tools
    )
    cfg = Config()
    banner = build_banner(model="m", cwd=Path("/tmp"), cfg=cfg)
    overflow = [t for t in banner.tools if t.name == "…"]
    assert len(overflow) == 1
    assert overflow[0].hidden_count > 0


def test_per_toolset_tool_count_capped():
    """Each visible toolset preview is capped at _MAX_TOOLS_PER_SET
    so the info panel doesn't blow up width-wise."""
    cfg = Config()
    banner = build_banner(model="m", cwd=Path("/tmp"), cfg=cfg)
    for ts in banner.tools:
        if ts.name == "…":
            continue
        assert len(ts.tools) <= _MAX_TOOLS_PER_SET


def test_commands_hint_populated():
    cfg = Config()
    banner = build_banner(model="m", cwd=Path("/tmp"), cfg=cfg)
    # The hint should at least mention /help so the user can
    # discover the slash surface.
    assert "/help" in banner.commands_hint
