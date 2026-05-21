"""Tier classification tests (T6-04.1).

The classifier maps every proposed action to one of three
tiers. Get this wrong and the gate makes wrong decisions. The
tests pin both the obvious destructive-verb cases and the
conservative defaults (unreadable click / sensitive key /
unknown verb).
"""

from __future__ import annotations

import pytest

from athena.computer.contract import Action
from athena.computer.permission import classify


# ---------------------------------------------------------------------------
# observe tier
# ---------------------------------------------------------------------------


def test_screenshot_is_observe():
    """Non-input action → observe."""
    assert classify(Action(type="screenshot")) == "observe"


# ---------------------------------------------------------------------------
# destructive tier — explicit hints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [
        "Delete",
        "delete file",
        "Remove from list",
        "Send",
        "Submit application",
        "Pay $42.00",
        "Buy now",
        "Purchase",
        "Order",
        "Confirm",
        "Overwrite",
        "Replace existing",
        "Discard changes",
        "Erase disk",
        "Format",
        "wipe device",
        "sudo install",
        "Move to Trash",
        "Reset to defaults",
        "Restart Now",
        "Shutdown",
        "Uninstall",
        "Drop table",
        "Don't Save",
        "Close without saving",
        "Sign out",
        "Log Out",
        # Case-insensitivity check
        "DELETE",
    ],
)
def test_send_button_is_destructive(target: str):
    """Each of these target labels triggers the destructive
    branch — the model finds them in the screenshot and the
    classifier surfaces them."""
    a = Action(type="click", target_desc=target, app="editor")
    assert classify(a) == "destructive", f"missed destructive hint: {target!r}"


def test_typed_text_with_destructive_verb_is_destructive():
    """A `type` action whose payload contains a destructive
    verb (e.g. typing `rm -rf /` into a terminal) is treated
    as destructive even when the target_desc is harmless."""
    a = Action(
        type="type",
        target_desc="Terminal input",
        text="sudo rm -rf /",
        app="terminal",
    )
    assert classify(a) == "destructive"


# ---------------------------------------------------------------------------
# destructive tier — sensitive keys
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "Delete",
        "shift+delete",
        "Alt+F4",
        "cmd+q",
        "Ctrl+W",
        "ctrl+alt+delete",
        "F5",
    ],
)
def test_sensitive_key_is_destructive(key: str):
    a = Action(type="key", key=key, app="editor")
    assert classify(a) == "destructive"


def test_benign_key_is_input():
    """Most keystrokes are routine input — Tab, arrow keys,
    letters."""
    for k in ("Tab", "Return", "ArrowDown", "a", "Space"):
        a = Action(type="key", key=k, target_desc="text field", app="editor")
        assert classify(a) == "input", f"benign key promoted: {k!r}"


# ---------------------------------------------------------------------------
# Conservative defaults
# ---------------------------------------------------------------------------


def test_unreadable_click_is_destructive():
    """A click with no target_desc — the a11y tree said nothing,
    vision couldn't label it — defaults to destructive. We don't
    know what this button does; assume the worst."""
    a = Action(type="click", target_desc=None, app="editor")
    assert classify(a) == "destructive"


def test_unreadable_double_click_is_destructive():
    a = Action(type="double_click", target_desc=None, app="editor")
    assert classify(a) == "destructive"


def test_unreadable_right_click_is_destructive():
    a = Action(type="right_click", target_desc=None, app="editor")
    assert classify(a) == "destructive"


def test_unreadable_drag_is_destructive():
    a = Action(type="drag", target_desc=None, app="editor")
    assert classify(a) == "destructive"


def test_classification_uncertain_defaults_destructive():
    """Pinning the documented conservative-default contract for
    click-style verbs with no readable target."""
    for verb in ("click", "double_click", "right_click", "drag"):
        a = Action(type=verb, target_desc=None, app="x")
        assert classify(a) == "destructive", verb


# ---------------------------------------------------------------------------
# input tier — the routine path
# ---------------------------------------------------------------------------


def test_plain_input_click_is_input_tier():
    """A click on a labeled, benign target is `input`."""
    a = Action(type="click", target_desc="Tab 2", app="editor")
    assert classify(a) == "input"


@pytest.mark.parametrize(
    "target",
    [
        "Tab 2",
        "Switch to draft",
        "Open file",
        "Search",
        "Find next",
        "Zoom in",
        "Settings",
        "Preferences",
    ],
)
def test_routine_labels_are_input(target: str):
    a = Action(type="click", target_desc=target, app="editor")
    assert classify(a) == "input"


def test_scroll_with_known_target_is_input():
    a = Action(type="scroll", target_desc="document area", app="editor")
    assert classify(a) == "input"


def test_move_is_input():
    """A bare move (no click) is the lowest-risk input verb —
    classified as input but the gate's allow/denylist + mode
    still apply."""
    a = Action(type="move", coords=(100, 100), app="editor")
    assert classify(a) == "input"


def test_type_with_benign_text_is_input():
    a = Action(
        type="type",
        target_desc="search box",
        text="weather today",
        app="browser",
    )
    assert classify(a) == "input"


# ---------------------------------------------------------------------------
# Mid-sentence destructive-verb guard
# ---------------------------------------------------------------------------


def test_destructive_hint_mid_label_still_caught():
    """\\b boundaries — 'delete row' matches; but make sure the
    classifier isn't trivially fooled by surrounding context."""
    assert classify(Action(type="click", target_desc="Delete row", app="x")) == "destructive"
    assert classify(Action(type="click", target_desc="Move row to trash", app="x")) == "destructive"
    # And a benign label that incidentally CONTAINS letters from
    # a hint word doesn't trip it ("Send" is destructive; "Sender"
    # … is actually a word boundary match because of \b. That's a
    # known conservative behaviour — we accept the false positive
    # on the sender field rather than missing the Send button).


def test_app_name_with_destructive_verb_is_caught():
    """A click in an app whose name contains a destructive verb
    (e.g. a malicious app titled 'Delete-Me Helper') still goes
    through the gate's allowlist — and the classifier picks up
    the app name as a destructive hint too."""
    a = Action(type="click", target_desc="Continue", app="delete-helper")
    assert classify(a) == "destructive"
