"""Textual labeling TUI over the batch driver (T3-05R.3).

A keyboard-driven trajectory labeller that wraps
:class:`BatchReviewDriver`. Lives behind the optional ``train``
extra (``pip install "athena-coder[train]"`` pulls textual);
imports textual lazily so headless installs without the extra
still import this module — :func:`run_review_tui` raises a clear
error at call time.

Layout:

  Header: athena train review · N/total (P%) · est ~Xm
  Body:   the current trajectory (user/tool/assistant turns)
  Suggestion: classifier (+ optional skill-metrics enhancement)
  Footer: hotkeys per the active keymap

Default keymap (see :mod:`athena.transform.keymaps`):

  y / j   label good and advance
  n / k   label bad and advance
  p       label preference_pair
  s       skip (advance without persisting)
  space   toggle multi-select
  Y / N   batch-apply good / bad to selection
  enter   accept current suggestion
  h / ←   step back
  l / →   step forward
  ctrl+z  undo last label
  /       filter (skill / status) [reserved]
  q       quit
  ?       help [reserved]

Quit / unreviewed both exit cleanly — the sidecar writes happen
incrementally during the session so there's no save-on-exit step.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .batch_driver import BatchReviewDriver
from .classifier import Label, Trajectory

logger = logging.getLogger(__name__)


def _require_textual() -> Any:
    """Lazy import the textual symbols we need. Returns a dict-like
    namespace; raises a friendly error when textual isn't installed."""
    try:
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import Vertical
        from textual.widgets import Footer, Header, Static
    except ImportError as e:
        raise RuntimeError(
            "athena train review --tui requires textual. Install with:\n\n"
            '    pipx install --force "athena-coder[train]"\n'
            "\nOr pass --no-tui to use the existing prompt-based labeller."
        ) from e
    return {
        "App": App,
        "ComposeResult": ComposeResult,
        "Binding": Binding,
        "Vertical": Vertical,
        "Footer": Footer,
        "Header": Header,
        "Static": Static,
    }


SuggestionFn = Callable[[Trajectory], "Suggestion | None"]


from dataclasses import dataclass


@dataclass
class Suggestion:
    """A label recommendation surfaced above the footer.

    ``source`` is human-readable provenance (``classifier``,
    ``metrics``); the TUI renders it so the user knows whether the
    suggestion came from heuristics or skill-history data."""

    label: Label
    source: str = "classifier"
    confidence: float | None = None


def default_suggestion(trajectory: Trajectory) -> Suggestion | None:
    """The baseline suggestion: classifier output, no enhancement.

    Returns ``None`` when ``auto_label`` is the no-signal default
    ``"unreviewed"`` — no point recommending the placeholder."""
    if trajectory.auto_label in ("good", "bad", "preference_pair"):
        return Suggestion(label=trajectory.auto_label, source="classifier")
    return None


# ---------------------------------------------------------------------------
# The textual App (lazy-built so importing this module never requires textual)
# ---------------------------------------------------------------------------


def make_app(
    driver: BatchReviewDriver,
    *,
    suggestion_fn: SuggestionFn = default_suggestion,
    keymap: str = "default",
):
    """Build the textual App for this driver. Returns an App
    instance; the caller decides whether to ``app.run()`` (live) or
    ``async with app.run_test()`` (pilot-driven test)."""
    syms = _require_textual()
    App = syms["App"]
    ComposeResult = syms["ComposeResult"]
    Binding = syms["Binding"]
    Vertical = syms["Vertical"]
    Footer = syms["Footer"]
    Header = syms["Header"]
    Static = syms["Static"]

    from .keymaps import get_keymap

    keymap_dict = get_keymap(keymap)

    # Build textual Binding tuples from the keymap. Each entry maps
    # a key string ("y", "ctrl+z", "space", …) to an action name
    # ("label_good", "undo", …) that textual dispatches to
    # ``action_<name>`` on the App.
    bindings = [
        Binding(key, action, action.replace("_", " "), show=False)
        for key, action in keymap_dict.items()
    ]

    class _LabelingApp(App):
        TITLE = "athena train review"
        BINDINGS = bindings

        def __init__(self) -> None:
            super().__init__()
            self.driver = driver
            self.suggestion_fn = suggestion_fn
            self._label_timestamps: list[float] = []
            self.last_message: str = ""

        # ---- layout ----

        def compose(self) -> ComposeResult:
            yield Header()
            yield Vertical(
                Static(id="status"),
                Static(id="trajectory"),
                Static(id="suggestion"),
                Static(id="message"),
            )
            yield Footer()

        def on_mount(self) -> None:
            self._render()

        # ---- actions (keymap → action_<name>) ----

        def action_label_good(self) -> None:
            self._label("good")

        def action_label_bad(self) -> None:
            self._label("bad")

        def action_label_preference_pair(self) -> None:
            self._label("preference_pair")

        def action_skip(self) -> None:
            self._label("skip")

        def action_accept_suggestion(self) -> None:
            item = self.driver.current()
            if item is None:
                return
            sug = self.suggestion_fn(item.trajectory)
            if sug is None:
                self.last_message = "no suggestion to accept"
                self._render()
                return
            self._label(sug.label)

        def action_toggle_select(self) -> None:
            self.driver.toggle_select()
            self._render()

        def action_batch_good(self) -> None:
            self._batch("good")

        def action_batch_bad(self) -> None:
            self._batch("bad")

        def action_go_back(self) -> None:
            self.driver.go_back()
            self._render()

        def action_go_forward(self) -> None:
            self.driver.go_forward()
            self._render()

        def action_undo(self) -> None:
            entry = self.driver.undo()
            if entry is None:
                self.last_message = "nothing to undo"
            else:
                self.last_message = (
                    f"undid: index {entry.item_index} "
                    f"({entry.new_label!r} → {entry.previous_label!r})"
                )
            self._render()

        def action_open_filter(self) -> None:
            # Reserved — filter widget is a follow-up; surface a hint
            # rather than no-op silently.
            self.last_message = "filter is a follow-up; not yet wired"
            self._render()

        def action_open_help(self) -> None:
            self.last_message = "see hotkey footer; full help is a follow-up"
            self._render()

        def action_quit(self) -> None:
            self.exit()

        # ---- internals ----

        def _label(self, label: Label) -> None:
            self.driver.label_current(label)
            self._label_timestamps.append(time.time())
            self.last_message = f"labelled {label!r}"
            self._render()

        def _batch(self, label: Label) -> None:
            n = self.driver.batch_label(label)
            self.last_message = f"batch-labelled {n} item(s) {label!r}"
            self._render()

        def _render(self) -> None:
            self.query_one("#status", Static).update(self._status_line())
            self.query_one("#trajectory", Static).update(self._trajectory_text())
            self.query_one("#suggestion", Static).update(self._suggestion_text())
            self.query_one("#message", Static).update(self.last_message)

        def _status_line(self) -> str:
            labelled, total = self.driver.progress
            current = self.driver.current_index + 1 if self.driver.items else 0
            sel = len(self.driver.selected)
            eta = self._eta_str()
            return f"  {current}/{total}  labelled {labelled}  selected {sel}  {eta}"

        def _trajectory_text(self) -> str:
            item = self.driver.current()
            if item is None:
                return "(no pending trajectories)"
            t = item.trajectory
            lines: list[str] = [
                f"session {t.session_id[:12]}  turns {t.turn_start}-{t.turn_end}  "
                f"current label: {t.user_label}",
                "",
            ]
            for m in t.turns:
                role = (m.get("role") or "?").upper()
                content = m.get("content") or ""
                if isinstance(content, list):
                    content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                snippet = (content or "").strip()
                if len(snippet) > 400:
                    snippet = snippet[:400] + "…"
                lines.append(f"[{role}] {snippet}")
                for tc in m.get("tool_calls") or []:
                    fn = (tc.get("function") or {}).get("name", "?")
                    lines.append(f"  ↳ tool_call: {fn}")
            if self.driver.current_index in self.driver.selected:
                lines.insert(0, "[SELECTED]")
            return "\n".join(lines)

        def _suggestion_text(self) -> str:
            item = self.driver.current()
            if item is None:
                return ""
            sug = self.suggestion_fn(item.trajectory)
            if sug is None:
                return "auto-suggestion: (none)"
            tail = f" (confidence {sug.confidence:.0%})" if sug.confidence is not None else ""
            return f"auto-suggestion: {sug.label}  [source: {sug.source}]{tail}"

        def _eta_str(self) -> str:
            """EWMA estimate over the last 10 inter-label intervals."""
            if len(self._label_timestamps) < 2:
                return ""
            ts = self._label_timestamps[-10:]
            intervals = [ts[i] - ts[i - 1] for i in range(1, len(ts))]
            if not intervals:
                return ""
            avg = sum(intervals) / len(intervals)
            remaining = max(0, self.driver.total - (self.driver.current_index + 1))
            eta_s = int(remaining * avg)
            mins, secs = divmod(eta_s, 60)
            return f"eta ~{mins}m{secs:02d}s"

    return _LabelingApp()


def run_review_tui(
    *,
    profile_dir: Path,
    since_days: int = 30,
    keymap: str = "default",
    suggestion_fn: SuggestionFn = default_suggestion,
) -> int:
    """Entry point called by ``athena train review`` when ``--no-tui``
    is absent. Builds a ReviewSession, materialises the driver, and
    runs the textual app blocking until the user quits."""
    from .review import ReviewSession

    session = ReviewSession(profile_dir, since_days=since_days)
    try:
        driver = BatchReviewDriver.from_review_session(session)
        if not driver.items:
            return _no_trajectories_msg()
        app = make_app(driver, suggestion_fn=suggestion_fn, keymap=keymap)
        app.run()
        return 0
    finally:
        session.close()


def _no_trajectories_msg() -> int:
    import sys

    sys.stdout.write("no trajectories pending review.\n")
    return 0
