"""Interactive trajectory review.

:class:`ReviewSession` walks every unreviewed trajectory from sessions in
the active profile (filtered by ``since_days``) and persists the user's
label decisions to a sidecar file per session:

    <profile_dir>/labels/<session_id>.json

The file is a flat dict mapping ``"<turn_start>-<turn_end>"`` → label.
Storing labels next to sessions (rather than inside the session JSONL)
keeps the JSONL append-only — labels can change, but the session
transcript doesn't.

The TUI is in :meth:`start`, which delegates the actual user prompt to a
:class:`LabelPrompt` callable. Tests substitute a scripted prompt to
drive the loop deterministically.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..sessions.store import SessionMeta, SessionStore
from .classifier import Label, Trajectory, auto_classify, extract_trajectories

logger = logging.getLogger(__name__)


LabelPrompt = Callable[[Trajectory, Label], Label]
"""Signature for the user-prompt callable.

Receives the trajectory and its auto-suggested label, returns the chosen
``Label``. Implementations may render the trajectory however they like
(rich console, plain text, etc.). Returning ``"skip"`` advances to the
next trajectory without persisting a user label; ``"unreviewed"`` is a
no-op marker for "the prompt was abandoned mid-way" — the loop quits.
"""


def _trajectory_key(t: Trajectory) -> str:
    return f"{t.turn_start}-{t.turn_end}"


def labels_dir(profile_dir: Path) -> Path:
    return profile_dir / "labels"


def labels_path(profile_dir: Path, session_id: str) -> Path:
    return labels_dir(profile_dir) / f"{session_id}.json"


def load_labels(profile_dir: Path, session_id: str) -> dict[str, str]:
    """Return the persisted labels for a session, or an empty dict."""
    p = labels_path(profile_dir, session_id)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_label(profile_dir: Path, session_id: str, key: str, label: Label) -> None:
    """Persist a single trajectory label to the session's labels file."""
    p = labels_path(profile_dir, session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = load_labels(profile_dir, session_id)
    existing[key] = label
    p.write_text(
        json.dumps(existing, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


@dataclass
class ReviewProgress:
    seen: int = 0
    labeled: int = 0
    skipped: int = 0
    quit_early: bool = False


class ReviewSession:
    """Drives a single review pass over recent sessions."""

    def __init__(
        self,
        profile_dir: Path,
        *,
        since_days: int = 30,
        store: SessionStore | None = None,
        include_auto_labels: bool = False,
    ):
        self.profile_dir = Path(profile_dir)
        self.since_days = since_days
        self.include_auto_labels = include_auto_labels
        self._store = store or SessionStore(self.profile_dir)
        self._owns_store = store is None

    # ---- Enumeration ----

    def pending(self) -> Iterator[tuple[SessionMeta, Trajectory]]:
        """Yield ``(session_meta, trajectory)`` for every trajectory not yet
        user-labeled. Iterates sessions newest-first; within each session,
        in turn order.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.since_days)
        sessions = self._store.list_sessions(limit=10_000)
        for meta in sessions:
            if meta.started_at < cutoff:
                continue
            try:
                messages = list(self._store.load(meta.session_id))
            except (OSError, FileNotFoundError):
                continue
            existing = load_labels(self.profile_dir, meta.session_id)
            trajectories = extract_trajectories(meta.session_id, messages)
            # Walk pairwise so auto_classify gets the next user message.
            for idx, t in enumerate(trajectories):
                next_user = _next_user_message(trajectories, idx)
                t.auto_label = auto_classify(t, next_user_message=next_user)
                # Hydrate user_label from disk if present.
                key = _trajectory_key(t)
                if key in existing:
                    t.user_label = existing[key]  # type: ignore[assignment]
                if t.user_label != "unreviewed":
                    continue
                yield meta, t

    # ---- Driver ----

    def start(self, prompt: LabelPrompt) -> ReviewProgress:
        """Iterate :meth:`pending` and ask ``prompt`` for each trajectory.

        ``prompt`` returns the chosen ``Label``. The loop persists every
        non-``unreviewed`` label and stops on the first ``unreviewed``
        return (the "quit" sentinel).
        """
        progress = ReviewProgress()
        for meta, t in self.pending():
            progress.seen += 1
            try:
                chosen = prompt(t, t.auto_label)
            except KeyboardInterrupt:
                progress.quit_early = True
                return progress
            if chosen == "unreviewed":
                progress.quit_early = True
                return progress
            if chosen == "skip":
                progress.skipped += 1
                continue
            save_label(self.profile_dir, meta.session_id, _trajectory_key(t), chosen)
            progress.labeled += 1
        return progress

    def close(self) -> None:
        if self._owns_store:
            try:
                self._store.close()
            except Exception:
                pass


def _next_user_message(trajectories: list[Trajectory], idx: int) -> dict[str, Any] | None:
    """For trajectory ``idx``, return the first ``user`` message of the
    following trajectory (the natural "follow-up" signal). ``None`` if
    this is the last trajectory."""
    if idx + 1 >= len(trajectories):
        return None
    nxt = trajectories[idx + 1]
    for m in nxt.turns:
        if m.get("role") == "user":
            return m
    return None


# ---- Default TUI prompt -------------------------------------------------


_LABEL_BY_KEY: dict[str, Label] = {
    "g": "good",
    "b": "bad",
    "p": "preference_pair",
    "s": "skip",
    "q": "unreviewed",  # quit sentinel
}


def default_prompt(trajectory: Trajectory, suggestion: Label) -> Label:
    """Default rich+prompt_toolkit prompt. Tests pass their own callable
    so this code path isn't exercised in CI; the real TUI lives behind
    a lazy import."""
    from prompt_toolkit import prompt as pt_prompt
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    console.print(
        Panel.fit(
            _render_trajectory(trajectory),
            title=f"session {trajectory.session_id[:8]} | turns "
            f"{trajectory.turn_start}-{trajectory.turn_end}",
            subtitle=f"auto: {suggestion}",
        )
    )
    while True:
        raw = pt_prompt("[g]ood [b]ad [p]ref [s]kip [q]uit > ").strip().lower()
        if raw in _LABEL_BY_KEY:
            return _LABEL_BY_KEY[raw]
        console.print("[yellow]choose one of g / b / p / s / q[/]")


def _render_trajectory(t: Trajectory) -> str:
    """Plain-string rendering (no rich markup). The Panel wraps it."""
    lines: list[str] = []
    for m in t.turns:
        role = m.get("role", "?")
        content = m.get("content") or ""
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        snippet = (content or "").strip()
        if len(snippet) > 400:
            snippet = snippet[:400] + "…"
        lines.append(f"[{role.upper()}] {snippet}")
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function", {}).get("name", "?")
            lines.append(f"  ↳ tool_call: {fn}")
    return "\n".join(lines)
