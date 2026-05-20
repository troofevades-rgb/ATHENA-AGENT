"""Tests for athena.transform.review_tui (T3-05R.3).

Skips cleanly when the optional ``textual`` dep isn't installed —
matches the pattern athena uses for other optional surfaces
(observability, gateway). The CLI's --no-tui path is exercised
without needing textual at all.
"""

from __future__ import annotations

import pytest

textual = pytest.importorskip("textual")  # noqa: F841 — guards every test below

from pathlib import Path

from athena.transform.batch_driver import BatchItem, BatchReviewDriver
from athena.transform.classifier import Trajectory
from athena.transform.review import load_labels
from athena.transform.review_tui import (
    Suggestion,
    default_suggestion,
    make_app,
)


def _meta(session_id: str = "s1"):
    from athena.sessions.store import SessionMeta

    return SessionMeta(
        session_id=session_id,
        profile="default",
        model="m",
        workspace="/tmp",
    )


def _traj(start: int = 0, end: int = 2, auto: str = "unreviewed") -> Trajectory:
    return Trajectory(
        session_id="s1",
        turn_start=start,
        turn_end=end,
        turns=[
            {"role": "user", "content": "do thing"},
            {"role": "assistant", "content": "done"},
        ],
        auto_label=auto,  # type: ignore[arg-type]
    )


def _driver(tmp_path: Path, *items_kwargs) -> BatchReviewDriver:
    items = [BatchItem(meta=_meta(), trajectory=_traj(**kw)) for kw in items_kwargs or [{}]]
    return BatchReviewDriver(items, profile_dir=tmp_path)


# ---------------------------------------------------------------------------
# Hotkey dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_y_labels_good_and_advances(tmp_path: Path) -> None:
    driver = _driver(tmp_path, {"start": 0, "end": 2}, {"start": 3, "end": 5})
    app = make_app(driver)
    async with app.run_test() as pilot:
        await pilot.press("y")
        await pilot.pause()
    assert load_labels(tmp_path, "s1") == {"0-2": "good"}
    assert driver.current_index == 1


@pytest.mark.asyncio
async def test_n_labels_bad_and_advances(tmp_path: Path) -> None:
    driver = _driver(tmp_path, {"start": 0, "end": 2}, {"start": 3, "end": 5})
    app = make_app(driver)
    async with app.run_test() as pilot:
        await pilot.press("n")
        await pilot.pause()
    assert load_labels(tmp_path, "s1") == {"0-2": "bad"}


@pytest.mark.asyncio
async def test_p_labels_preference_pair(tmp_path: Path) -> None:
    driver = _driver(tmp_path, {"start": 0, "end": 2})
    app = make_app(driver)
    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()
    assert load_labels(tmp_path, "s1") == {"0-2": "preference_pair"}


@pytest.mark.asyncio
async def test_s_skip_does_not_persist(tmp_path: Path) -> None:
    driver = _driver(tmp_path, {"start": 0, "end": 2}, {"start": 3, "end": 5})
    app = make_app(driver)
    async with app.run_test() as pilot:
        await pilot.press("s")
        await pilot.pause()
    # Skip never writes; the sidecar stays empty.
    assert load_labels(tmp_path, "s1") == {}
    assert driver.current_index == 1


@pytest.mark.asyncio
async def test_space_then_capital_Y_batch_labels(tmp_path: Path) -> None:
    driver = _driver(
        tmp_path,
        {"start": 0, "end": 2},
        {"start": 3, "end": 5},
        {"start": 6, "end": 8},
    )
    app = make_app(driver)
    async with app.run_test() as pilot:
        await pilot.press("space")  # select index 0
        await pilot.press("l")  # advance to index 1
        await pilot.press("space")  # select index 1
        await pilot.press("Y")  # batch-good selection
        await pilot.pause()
    data = load_labels(tmp_path, "s1")
    assert data == {"0-2": "good", "3-5": "good"}
    assert driver.selected == set()


@pytest.mark.asyncio
async def test_ctrl_z_undoes(tmp_path: Path) -> None:
    driver = _driver(tmp_path, {"start": 0, "end": 2})
    app = make_app(driver)
    async with app.run_test() as pilot:
        await pilot.press("y")
        await pilot.pause()
        assert load_labels(tmp_path, "s1") == {"0-2": "good"}
        await pilot.press("ctrl+z")
        await pilot.pause()
    assert load_labels(tmp_path, "s1") == {}
    # Cursor returns to the undone trajectory.
    assert driver.current_index == 0


@pytest.mark.asyncio
async def test_enter_accepts_suggestion(tmp_path: Path) -> None:
    # auto_label preset to "good" so the classifier suggestion fires
    driver = _driver(tmp_path, {"start": 0, "end": 2, "auto": "good"})
    app = make_app(driver)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
    assert load_labels(tmp_path, "s1") == {"0-2": "good"}


@pytest.mark.asyncio
async def test_enter_with_no_suggestion_is_noop(tmp_path: Path) -> None:
    """``auto_label == 'unreviewed'`` → default_suggestion returns
    None → enter shouldn't persist anything."""
    driver = _driver(tmp_path, {"start": 0, "end": 2, "auto": "unreviewed"})
    app = make_app(driver)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
    assert load_labels(tmp_path, "s1") == {}


@pytest.mark.asyncio
async def test_h_steps_back(tmp_path: Path) -> None:
    driver = _driver(tmp_path, {"start": 0, "end": 2}, {"start": 3, "end": 5})
    driver.current_index = 1
    app = make_app(driver)
    async with app.run_test() as pilot:
        await pilot.press("h")
        await pilot.pause()
    assert driver.current_index == 0


@pytest.mark.asyncio
async def test_l_steps_forward(tmp_path: Path) -> None:
    driver = _driver(tmp_path, {"start": 0, "end": 2}, {"start": 3, "end": 5})
    app = make_app(driver)
    async with app.run_test() as pilot:
        await pilot.press("l")
        await pilot.pause()
    assert driver.current_index == 1


@pytest.mark.asyncio
async def test_q_quits(tmp_path: Path) -> None:
    driver = _driver(tmp_path, {"start": 0, "end": 2})
    app = make_app(driver)
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
    # The app exits cleanly; no labels persisted (we didn't label).
    assert load_labels(tmp_path, "s1") == {}


# ---------------------------------------------------------------------------
# Progress counters update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_counts_update(tmp_path: Path) -> None:
    driver = _driver(
        tmp_path,
        {"start": 0, "end": 2},
        {"start": 3, "end": 5},
        {"start": 6, "end": 8},
    )
    app = make_app(driver)
    async with app.run_test() as pilot:
        await pilot.press("y")
        await pilot.press("y")
        await pilot.pause()
    labelled, total = driver.progress
    assert labelled == 2
    assert total == 3


# ---------------------------------------------------------------------------
# Alternative keymaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_keymap_uses_g_for_good(tmp_path: Path) -> None:
    driver = _driver(tmp_path, {"start": 0, "end": 2}, {"start": 3, "end": 5})
    app = make_app(driver, keymap="basic")
    async with app.run_test() as pilot:
        await pilot.press("g")
        await pilot.pause()
    assert load_labels(tmp_path, "s1") == {"0-2": "good"}


@pytest.mark.asyncio
async def test_basic_keymap_u_for_undo(tmp_path: Path) -> None:
    driver = _driver(tmp_path, {"start": 0, "end": 2})
    app = make_app(driver, keymap="basic")
    async with app.run_test() as pilot:
        await pilot.press("g")
        await pilot.pause()
        assert load_labels(tmp_path, "s1") == {"0-2": "good"}
        await pilot.press("u")
        await pilot.pause()
    assert load_labels(tmp_path, "s1") == {}


# ---------------------------------------------------------------------------
# Suggestion module wiring
# ---------------------------------------------------------------------------


def test_default_suggestion_returns_classifier_label_when_set() -> None:
    t = _traj(auto="good")
    s = default_suggestion(t)
    assert s == Suggestion(label="good", source="classifier")


def test_default_suggestion_returns_none_when_unreviewed() -> None:
    assert default_suggestion(_traj(auto="unreviewed")) is None


@pytest.mark.asyncio
async def test_custom_suggestion_fn_drives_enter(tmp_path: Path) -> None:
    """A custom SuggestionFn (T3-06 enhancer signature) supplies a
    different label and Enter accepts it."""
    driver = _driver(tmp_path, {"start": 0, "end": 2, "auto": "unreviewed"})

    def custom(_t) -> Suggestion:
        return Suggestion(label="bad", source="custom", confidence=0.99)

    app = make_app(driver, suggestion_fn=custom)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
    assert load_labels(tmp_path, "s1") == {"0-2": "bad"}


# ---------------------------------------------------------------------------
# --no-tui fallback in the CLI
# ---------------------------------------------------------------------------


def test_no_tui_flag_uses_default_prompt(tmp_path: Path, monkeypatch) -> None:
    """When --no-tui is passed (or textual is missing), the CLI
    routes to _cmd_review_classic which calls ReviewSession.start
    with default_prompt. We don't need textual to verify this — just
    that the CLI dispatch picks the classic path."""
    from athena.cli.train import _cmd_review

    called = {"classic": False, "tui": False}

    def fake_classic(profile_dir, args):
        called["classic"] = True
        return 0

    def fake_tui(**_kwargs):
        called["tui"] = True
        return 0

    monkeypatch.setattr("athena.cli.train._cmd_review_classic", fake_classic)
    monkeypatch.setattr("athena.transform.review_tui.run_review_tui", fake_tui)

    class _Args:
        profile = "default"
        since_days = 30
        no_tui = True
        keymap = "default"

    _cmd_review(_Args())
    assert called["classic"] is True
    assert called["tui"] is False
