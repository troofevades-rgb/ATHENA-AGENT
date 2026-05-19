"""Tests for athena.provenance — the write-origin ContextVar."""

import threading

import pytest

from athena.provenance import (
    BACKGROUND_REVIEW,
    CURATOR,
    FOREGROUND,
    MIGRATION,
    SYSTEM,
    get_current_write_origin,
    is_background,
    reset_current_write_origin,
    set_current_write_origin,
)


def test_default_origin_is_foreground():
    assert get_current_write_origin() == FOREGROUND


def test_set_and_reset_origin():
    token = set_current_write_origin(CURATOR)
    try:
        assert get_current_write_origin() == CURATOR
    finally:
        reset_current_write_origin(token)
    assert get_current_write_origin() == FOREGROUND


def test_unknown_origin_rejected():
    with pytest.raises(ValueError, match="unknown write_origin"):
        set_current_write_origin("not-a-real-origin")


def test_is_background_for_review_and_curator():
    assert is_background() is False

    for origin in (BACKGROUND_REVIEW, CURATOR):
        token = set_current_write_origin(origin)
        try:
            assert is_background() is True
        finally:
            reset_current_write_origin(token)

    for origin in (FOREGROUND, MIGRATION, SYSTEM):
        token = set_current_write_origin(origin)
        try:
            assert is_background() is False
        finally:
            reset_current_write_origin(token)


def test_origin_isolated_per_thread():
    """ContextVar values do NOT cross threads by default. A child thread starts
    fresh at FOREGROUND regardless of what the parent set, and the parent's
    value is unaffected by what the child sets."""
    parent_token = set_current_write_origin(CURATOR)
    try:
        seen_in_child: dict[str, str] = {}
        done = threading.Event()

        def child():
            seen_in_child["initial"] = get_current_write_origin()
            child_token = set_current_write_origin(MIGRATION)
            try:
                seen_in_child["after_set"] = get_current_write_origin()
            finally:
                reset_current_write_origin(child_token)
            done.set()

        t = threading.Thread(target=child)
        t.start()
        t.join(timeout=2.0)
        assert done.is_set(), "child thread did not complete"

        assert seen_in_child["initial"] == FOREGROUND
        assert seen_in_child["after_set"] == MIGRATION
        assert get_current_write_origin() == CURATOR
    finally:
        reset_current_write_origin(parent_token)
