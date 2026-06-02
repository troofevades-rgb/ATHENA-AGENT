"""Build a ``BannerEvent`` from athena's existing UI data sources.

Centralises the lookup so the TUI bundle never reads
``athena/_owl_art.txt`` or ``athena.ui.THEMES`` directly — those
stay Python's job. A future skin marketplace / web dashboard
plugs in here, not into the TUI.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .events import BannerEvent, ThemePalette, ToolSetSummary
from .owl_image import render_owl_pixels

if TYPE_CHECKING:
    from ..config import Config


# Tool catalog presentation matches the Rich-side info panel from
# ``athena/ui.py:_info_panel`` so the new TUI doesn't look like a
# different product mid-migration.
_PRIORITY_TOOLSETS = (
    "file",
    "shell",
    "skills",
    "memory",
    "media",
    "recall",
    "web",
    "core",
)
_MAX_VISIBLE_TOOLSETS = 8
_MAX_TOOLS_PER_SET = 4

# Photo-render target. The Ink Banner uses INFO_WIDTH=48 +
# GAP=2 for the right column, leaving ``term_cols - 50`` for
# the owl panel. Subtract another 4 for the owl panel's border
# + padding to get the inner content width — that's the cap we
# render to. Floor + ceiling guard against tiny / oversized
# terminals. Height is half the width to keep the figure
# roughly photo-aspect.
_OWL_WIDTH_MAX = 96  # 96 lets ~1280-wide terminals show full detail
_OWL_WIDTH_MIN = 24

# Owl mark style. The quadrant-photo path (render_owl_pixels over
# _owl_image.jpg) reduces to noise at banner cell counts — it "looks
# like nothing." The braille line-art mark (athena/_owl_art.txt) reads
# as a clean, deliberate owl and matches the Claude-Code / Codex
# text-forward aesthetic. Flip to False to restore the photo owl (the
# jpg is still bundled; this is the only switch needed).
_USE_BRAILLE_OWL = True


def _compute_photo_size(
    *,
    term_cols: int | None = None,
    term_rows: int | None = None,
) -> tuple[int, int]:
    """Pick an owl render size that fits the terminal.

    When ``term_cols`` is given (e.g. from a ResizeCommand sent
    by the live TUI), use it directly so the photo reflects the
    actual current terminal width — not the value
    ``shutil.get_terminal_size()`` happened to return at process
    spawn. Falls back to ``shutil`` for the initial banner before
    the TUI has reported its size.
    """
    if term_cols is not None and term_cols > 0:
        cols = term_cols
    else:
        import shutil

        try:
            cols = shutil.get_terminal_size((100, 30)).columns
        except (OSError, ValueError):
            cols = 100
    # 48 info + 2 gap + 4 owl panel chrome = 54 cells the owl
    # panel can't use. Cap at _OWL_WIDTH_MAX so we don't waste
    # render time on ultra-wide terminals (the source image
    # tops out around 72 cells of legible detail).
    inner = cols - 48 - 2 - 4
    width = max(_OWL_WIDTH_MIN, min(_OWL_WIDTH_MAX, inner))
    height = max(12, width // 2)
    return width, height


def build_banner(
    *,
    model: str,
    cwd: Path,
    cfg: Config,
    theme_name: str | None = None,
    term_cols: int | None = None,
    term_rows: int | None = None,
) -> BannerEvent:
    """Snapshot the data the TUI needs to render its banner. Pure
    function — does not mutate anything. Safe to call from any
    thread (no event-loop deps).

    ``term_cols`` / ``term_rows`` come from the live TUI's
    ResizeCommand on subsequent renders, so the owl photo matches
    the current terminal size. On the initial call (before any
    resize event) they're None and the renderer falls back to
    ``shutil.get_terminal_size()``.
    """
    # Theme resolution — fall back gracefully when the requested
    # theme is unknown so a typo in config.toml never crashes
    # session start.
    from .. import ui as _ui

    name = theme_name or getattr(cfg, "theme", None) or "phosphor"
    theme = _ui.THEMES.get(name) or _ui.THEMES["phosphor"]
    palette = ThemePalette(
        name=theme.name,
        description=theme.description,
        primary=theme.primary,
        primary_dim=theme.primary_dim,
        primary_faint=theme.primary_faint,
        accent=theme.accent,
        accent_dim=theme.accent_dim,
        gradient=list(theme.gradient),
    )

    owl_art = _load_owl_art()
    if _USE_BRAILLE_OWL:
        # Braille mark is the owl; skip the photo render entirely.
        owl_pixels = None
    else:
        photo_w, photo_h = _compute_photo_size(
            term_cols=term_cols,
            term_rows=term_rows,
        )
        owl_pixels = render_owl_pixels(photo_w, photo_h)
    tools = _collect_tools()

    return BannerEvent(
        model=model,
        cwd=str(cwd),
        theme=theme.name,
        tools=tools,
        owl_art=owl_art,
        owl_pixels=owl_pixels,
        palette=palette,
        commands_hint="/help · /theme · /goal · /board · /video · /exit",
    )


def _load_owl_art() -> list[str]:
    """Load the bundled owl artwork. Returns equal-width rows
    matching the Rich-side renderer's behavior. Empty list when
    the file is missing — TUI renders without an owl rather than
    crashing the banner."""
    art_path = Path(__file__).resolve().parent.parent / "_owl_art.txt"
    try:
        raw = art_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    if not raw:
        return []
    width = max(len(line) for line in raw)
    return [line.ljust(width) for line in raw]


def _collect_tools() -> list[ToolSetSummary]:
    """Read the current tool registry, grouped by toolset, sorted
    by the same priority list the Rich info panel uses. Returns
    a flattened list with hidden_count > 0 on the last visible
    entry when more toolsets exist than ``_MAX_VISIBLE_TOOLSETS``."""
    try:
        from ..tools.registry import all_tools
    except Exception:  # noqa: BLE001
        return []
    groups: dict[str, list[str]] = {}
    for tool in all_tools():
        groups.setdefault(tool.toolset, []).append(tool.name)
    ordered = [g for g in _PRIORITY_TOOLSETS if g in groups] + sorted(
        g for g in groups if g not in _PRIORITY_TOOLSETS
    )
    visible = ordered[:_MAX_VISIBLE_TOOLSETS]
    hidden = ordered[_MAX_VISIBLE_TOOLSETS:]
    summaries: list[ToolSetSummary] = []
    for name in visible:
        names = sorted(groups[name])
        summaries.append(
            ToolSetSummary(
                name=name,
                tools=names[:_MAX_TOOLS_PER_SET],
                hidden_count=max(0, len(names) - _MAX_TOOLS_PER_SET),
            )
        )
    if hidden:
        # Synthesize a final "+N more" entry. The TUI renders it
        # specially because the ``name`` is "…" not a real toolset.
        summaries.append(
            ToolSetSummary(
                name="…",
                tools=list(hidden),
                hidden_count=len(hidden),
            )
        )
    return summaries
