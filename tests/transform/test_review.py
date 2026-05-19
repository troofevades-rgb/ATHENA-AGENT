"""ReviewSession: enumeration, persistence, resume."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from athena.sessions.store import SessionMeta, SessionStore
from athena.transform.classifier import Label, Trajectory
from athena.transform.review import (
    ReviewSession,
    load_labels,
    save_label,
)

# ---- Helpers ----------------------------------------------------------


def _make_store(tmp_path: Path) -> SessionStore:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    return SessionStore(profile_dir)


def _write_session(
    store: SessionStore,
    session_id: str,
    messages: list[dict],
    *,
    model: str = "qwen2.5-coder:14b",
    started_at: datetime | None = None,
) -> None:
    """Open a session, append every message, close — easier than going
    through Agent in tests."""
    meta = SessionMeta(
        session_id=session_id,
        profile="default",
        model=model,
        workspace="/tmp",
        started_at=started_at or datetime.now(timezone.utc),
    )
    store.open_session(meta)
    for m in messages:
        store.append_turn(session_id, m)
    store.close_session(session_id)


def _user(text: str) -> dict:
    return {"role": "user", "content": text}


def _assistant(text: str) -> dict:
    return {"role": "assistant", "content": text}


# ---- save_label / load_labels -----------------------------------------


def test_save_and_load_labels_roundtrip(tmp_path: Path):
    profile = tmp_path / "p"
    save_label(profile, "s1", "0-1", "good")
    save_label(profile, "s1", "2-3", "bad")
    labels = load_labels(profile, "s1")
    assert labels == {"0-1": "good", "2-3": "bad"}


def test_load_labels_returns_empty_for_missing(tmp_path: Path):
    assert load_labels(tmp_path, "never_existed") == {}


def test_save_label_overwrites_prior_value(tmp_path: Path):
    save_label(tmp_path, "s1", "0-1", "good")
    save_label(tmp_path, "s1", "0-1", "bad")
    assert load_labels(tmp_path, "s1") == {"0-1": "bad"}


def test_load_labels_returns_empty_on_malformed_json(tmp_path: Path):
    """A corrupted labels file falls back to empty (don't crash review)."""
    target = tmp_path / "labels" / "s1.json"
    target.parent.mkdir(parents=True)
    target.write_text("not json", encoding="utf-8")
    assert load_labels(tmp_path, "s1") == {}


# ---- ReviewSession.pending -------------------------------------------


def test_pending_walks_unreviewed_trajectories(tmp_path: Path):
    store = _make_store(tmp_path)
    _write_session(store, "s1", [_user("a"), _assistant("b"), _user("c"), _assistant("d")])
    profile = store.profile_dir
    review = ReviewSession(profile, store=store)
    try:
        pending = list(review.pending())
    finally:
        review.close()
    # Two trajectories, both unreviewed → both yielded.
    assert len(pending) == 2
    assert pending[0][1].turn_start == 0
    assert pending[1][1].turn_start == 2


def test_pending_skips_already_reviewed(tmp_path: Path):
    store = _make_store(tmp_path)
    _write_session(store, "s1", [_user("a"), _assistant("b"), _user("c"), _assistant("d")])
    profile = store.profile_dir
    # Pre-label the first trajectory.
    save_label(profile, "s1", "0-1", "good")

    review = ReviewSession(profile, store=store)
    try:
        pending = list(review.pending())
    finally:
        review.close()
    # Only the second trajectory remains unreviewed.
    assert len(pending) == 1
    assert pending[0][1].turn_start == 2


def test_pending_respects_since_days_cutoff(tmp_path: Path):
    store = _make_store(tmp_path)
    old = datetime.now(timezone.utc).replace(year=2020)
    new = datetime.now(timezone.utc)
    _write_session(store, "old", [_user("a"), _assistant("b")], started_at=old)
    _write_session(store, "new", [_user("c"), _assistant("d")], started_at=new)

    review = ReviewSession(store.profile_dir, store=store, since_days=30)
    try:
        pending = list(review.pending())
    finally:
        review.close()
    sids = {meta.session_id for meta, _ in pending}
    assert sids == {"new"}


def test_pending_hydrates_auto_label(tmp_path: Path):
    """auto_classify runs over every trajectory and the result lands on the
    Trajectory before it's yielded."""
    store = _make_store(tmp_path)
    _write_session(
        store,
        "s1",
        [
            _user("read x"),
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "Read", "arguments": "{}"}}],
            },
            {"role": "tool", "name": "Read", "content": "Error: file not found"},
            _assistant("could not read"),
        ],
    )
    review = ReviewSession(store.profile_dir, store=store)
    try:
        pending = list(review.pending())
    finally:
        review.close()
    assert len(pending) == 1
    assert pending[0][1].auto_label == "bad"


# ---- ReviewSession.start ---------------------------------------------


def _scripted_prompt(labels: list[Label]):
    """Build a LabelPrompt that returns ``labels[i]`` on the i-th call.

    Raises IndexError if the loop asks for more decisions than scripted.
    """
    iter_ = iter(labels)

    def _prompt(trajectory: Trajectory, suggestion: Label) -> Label:
        return next(iter_)

    return _prompt


def test_start_persists_user_labels(tmp_path: Path):
    store = _make_store(tmp_path)
    _write_session(store, "s1", [_user("a"), _assistant("b"), _user("c"), _assistant("d")])
    review = ReviewSession(store.profile_dir, store=store)
    try:
        progress = review.start(_scripted_prompt(["good", "bad"]))
    finally:
        review.close()
    assert progress.seen == 2
    assert progress.labeled == 2
    labels = load_labels(store.profile_dir, "s1")
    assert labels == {"0-1": "good", "2-3": "bad"}


def test_start_skip_advances_without_labeling(tmp_path: Path):
    store = _make_store(tmp_path)
    _write_session(store, "s1", [_user("a"), _assistant("b"), _user("c"), _assistant("d")])
    review = ReviewSession(store.profile_dir, store=store)
    try:
        progress = review.start(_scripted_prompt(["skip", "good"]))
    finally:
        review.close()
    assert progress.skipped == 1
    assert progress.labeled == 1
    labels = load_labels(store.profile_dir, "s1")
    # Only one label was persisted (the second trajectory).
    assert labels == {"2-3": "good"}


def test_start_unreviewed_quits(tmp_path: Path):
    store = _make_store(tmp_path)
    _write_session(store, "s1", [_user("a"), _assistant("b"), _user("c"), _assistant("d")])
    review = ReviewSession(store.profile_dir, store=store)
    try:
        progress = review.start(_scripted_prompt(["unreviewed"]))
    finally:
        review.close()
    assert progress.quit_early is True
    assert progress.labeled == 0


def test_start_keyboardinterrupt_quits_cleanly(tmp_path: Path):
    store = _make_store(tmp_path)
    _write_session(store, "s1", [_user("a"), _assistant("b")])

    def _prompt(t, s):
        raise KeyboardInterrupt

    review = ReviewSession(store.profile_dir, store=store)
    try:
        progress = review.start(_prompt)
    finally:
        review.close()
    assert progress.quit_early is True


def test_resume_after_partial_review(tmp_path: Path):
    """Labeling stops mid-way; a second pass picks up where the first
    left off."""
    store = _make_store(tmp_path)
    _write_session(
        store,
        "s1",
        [
            _user("a"),
            _assistant("b"),
            _user("c"),
            _assistant("d"),
            _user("e"),
            _assistant("f"),
        ],
    )
    # First pass labels one, then quits.
    review = ReviewSession(store.profile_dir, store=store)
    try:
        first = review.start(_scripted_prompt(["good", "unreviewed"]))
    finally:
        review.close()
    assert first.labeled == 1

    # Second pass should only see two pending (not three).
    review2 = ReviewSession(store.profile_dir, store=store)
    try:
        pending = list(review2.pending())
    finally:
        review2.close()
    assert {t.turn_start for _, t in pending} == {2, 4}
