"""``athena board`` + ``/board`` — render the kanban (T6-06.3).

Two surfaces:

  ``athena board`` CLI — prints the columns, color-coded.
                          When textual is installed and the
                          terminal is a TTY, an interactive
                          TUI lights up; otherwise a plain
                          static render fires.

  ``/board`` slash — in-session display of the same projection.

The TUI is gated behind the ``athena[board]`` optional extra
(``textual`` dependency). When the dep isn't available, the CLI
prints the static render — `board_show` (the tool) and the CLI
core path don't depend on textual at all.

Read-only — neither surface mutates the store. Use TaskCreate /
TaskUpdate to move cards; the board re-renders on next launch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .. import ui
from . import command

# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _resolve_state(*, profile: str | None = None, goal_id: str | None = None) -> dict[str, Any]:
    """Build the projection state the renderers need.

    Returns ``{workspace, goal_id, counts, columns}`` — same
    shape as the ``board_show`` tool payload.
    """
    from ..config import load_config, profile_dir
    from ..tasks.board import column_counts, project_board
    from ..tasks.model import TaskStore, default_task_store_path

    cfg = load_config()
    prof = profile or getattr(cfg, "profile", None) or "default"
    pdir = profile_dir(prof)
    store_path = default_task_store_path(cfg, pdir)
    store = TaskStore(path=store_path)

    workspace = _active_workspace()
    cols = project_board(
        store,
        workspace=workspace or None,
        goal_id=goal_id or None,
    )
    return {
        "workspace": workspace,
        "goal_id": goal_id or None,
        "counts": column_counts(cols),
        "columns": cols,
        "store_path": store_path,
    }


def _active_workspace() -> str:
    """Workspace from file_ops at call time — same source the
    TaskCreate/Update/List tools use. Empty string when nothing
    has bound a workspace yet."""
    try:
        from ..tools import file_ops

        return str(file_ops._WORKSPACE)
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Static renderer (no extra deps)
# ---------------------------------------------------------------------------


_COLUMN_DISPLAY: tuple[tuple[str, str, str], ...] = (
    # (status, label, colour)
    ("todo", "TODO", "yellow"),
    ("doing", "DOING", "cyan"),
    ("blocked", "BLOCKED", "red"),
    ("done", "DONE", "green"),
)


def _print_static(state: dict[str, Any]) -> None:
    """Plain (still pretty) text render — works in any terminal,
    no optional deps."""
    counts = state["counts"]
    columns = state["columns"]
    workspace = state.get("workspace") or "(no workspace)"
    goal_id = state.get("goal_id")

    header_bits: list[str] = [f"[bold]board[/] · workspace: {workspace}"]
    if goal_id:
        header_bits.append(f"goal: {goal_id}")
    header_bits.append(f"store: {state['store_path']}")
    ui.console.print("  ".join(header_bits))
    ui.console.print(
        "  ".join(
            f"[{colour}]{label} ({counts.get(status, 0)})[/]"
            for status, label, colour in _COLUMN_DISPLAY
        )
    )

    for status, label, colour in _COLUMN_DISPLAY:
        cards = columns.get(status, [])
        if not cards:
            continue
        ui.console.print(f"\n[bold {colour}]{label}[/]")
        for card in cards:
            badge = " 🎯" if card.get("goal_id") else ""
            ui.console.print(f"  • {card['title']}{badge}  [dim]{card['id']}[/]")
            note = (card.get("note") or "").strip()
            if note:
                # First note line under the title (subtle).
                first = note.splitlines()[0]
                if first and first != card["title"]:
                    ui.console.print(f"      [dim]{first}[/]")
    if all(not columns.get(c, []) for c, _, _ in _COLUMN_DISPLAY):
        ui.console.print("\n[dim](no tasks — use TaskCreate or set a /goal)[/]")


# ---------------------------------------------------------------------------
# TUI (textual) — optional
# ---------------------------------------------------------------------------


def _try_run_tui(state: dict[str, Any]) -> bool:
    """Run the textual TUI if available. Returns True on
    success, False when textual isn't installed (caller falls
    back to static)."""
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Footer, Header, Static
    except ImportError:
        return False

    class _BoardApp(App[Any]):
        CSS = """
        Screen { background: $surface; }
        .col { width: 1fr; height: 1fr; padding: 1; border: solid $primary; }
        .col-todo    { border: solid yellow; }
        .col-doing   { border: solid cyan; }
        .col-blocked { border: solid red; }
        .col-done    { border: solid green; }
        .col-title { text-style: bold; padding-bottom: 1; }
        .card { padding-bottom: 1; }
        """
        BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]
        TITLE = "athena board"

        def __init__(self) -> None:
            super().__init__()
            self.state = state

        def compose(self) -> ComposeResult:
            yield Header()
            workspace = self.state.get("workspace") or "(no workspace)"
            yield Static(f"workspace: {workspace}    goal: {self.state.get('goal_id') or '(any)'}")
            with Horizontal():
                for status, label, _colour in _COLUMN_DISPLAY:
                    cards = self.state["columns"].get(status, [])
                    body_lines = [f"[b]{label} ({len(cards)})[/]"]
                    for card in cards:
                        badge = " 🎯" if card.get("goal_id") else ""
                        body_lines.append(f"• {card['title']}{badge}")
                    yield Static(
                        "\n".join(body_lines),
                        classes=f"col col-{status}",
                    )
            yield Footer()

        def action_refresh(self) -> None:
            """Re-resolve the state and re-mount the columns.
            A simple cheat: re-launch via the parent loop's
            re-run pattern. For v1 we just remount."""
            self.state = _resolve_state(goal_id=self.state.get("goal_id"))
            self.refresh()

    _BoardApp().run()
    return True


# ---------------------------------------------------------------------------
# Slash command (in-session)
# ---------------------------------------------------------------------------


@command("board")
def cmd_board(agent, arg: str = "") -> str:
    """``/board`` subcommands:

    /board                  show the board (default)
    /board goal:<id>        filter to one goal's cards
    /board clear            delete every live task in this workspace
                            (archive untouched — recoverable on demand)
    /board clear --all      drop everything across all goals (same as
                            ``clear`` today; reserved for future
                            per-goal scoping)
    """
    arg = (arg or "").strip()

    # /board clear — wipe live tasks. Archive (if any) stays intact;
    # leftover aspirational tasks from prior sessions otherwise sit
    # forever in context and confuse the model on every reload.
    if arg == "clear" or arg.startswith("clear "):
        from ..config import load_config, profile_dir
        from ..tasks.model import TaskStore, default_task_store_path

        cfg = load_config()
        prof = getattr(cfg, "profile", None) or "default"
        pdir = profile_dir(prof)
        store = TaskStore(path=default_task_store_path(cfg, pdir))
        n = store.clear()
        if n == 0:
            ui.info("board already empty")
        else:
            ui.info(f"cleared {n} task(s) from the board")
        return ""

    goal_id = None
    if arg.startswith("goal:"):
        goal_id = arg[len("goal:") :].strip() or None
    state = _resolve_state(goal_id=goal_id)
    _print_static(state)
    return ""


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="athena board",
        description="Show the persisted task kanban for this workspace.",
    )
    ap.add_argument(
        "--goal",
        default=None,
        help="Filter to a single goal's cards (the goal id).",
    )
    ap.add_argument(
        "--profile",
        default=None,
        help="Profile name (default: cfg.profile).",
    )
    ap.add_argument(
        "--static",
        action="store_true",
        help=("Force the plain text render (skip the textual TUI even if it's installed)."),
    )
    args = ap.parse_args(argv)

    state = _resolve_state(profile=args.profile, goal_id=args.goal)
    if args.static or not sys.stdout.isatty():
        _print_static(state)
        return 0

    # Try TUI; fall back to static render when textual isn't
    # installed.
    if _try_run_tui(state):
        return 0
    _print_static(state)
    return 0
