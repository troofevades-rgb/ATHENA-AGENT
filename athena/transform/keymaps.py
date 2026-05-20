"""Keymap definitions for the labeling TUI (T3-05R.3).

Three pre-defined maps keyed by name. The TUI uses these to build
textual ``Binding`` tuples at app construction time.

Action names are stable across keymaps so swapping doesn't change
the underlying dispatch — only which keys reach which action.
"""

from __future__ import annotations

# Action names the TUI implements as ``action_<name>``.
LABEL_GOOD = "label_good"
LABEL_BAD = "label_bad"
LABEL_PREFERENCE_PAIR = "label_preference_pair"
SKIP = "skip"
TOGGLE_SELECT = "toggle_select"
BATCH_GOOD = "batch_good"
BATCH_BAD = "batch_bad"
ACCEPT_SUGGESTION = "accept_suggestion"
GO_BACK = "go_back"
GO_FORWARD = "go_forward"
UNDO = "undo"
OPEN_FILTER = "open_filter"
OPEN_HELP = "open_help"
QUIT = "quit"


DEFAULT_KEYMAP: dict[str, str] = {
    "y": LABEL_GOOD,
    "j": LABEL_GOOD,
    "n": LABEL_BAD,
    "k": LABEL_BAD,
    "p": LABEL_PREFERENCE_PAIR,
    "s": SKIP,
    "space": TOGGLE_SELECT,
    "Y": BATCH_GOOD,
    "N": BATCH_BAD,
    "enter": ACCEPT_SUGGESTION,
    "h": GO_BACK,
    "left": GO_BACK,
    "l": GO_FORWARD,
    "right": GO_FORWARD,
    "ctrl+z": UNDO,
    "slash": OPEN_FILTER,
    "question_mark": OPEN_HELP,
    "q": QUIT,
}


VIM_KEYMAP: dict[str, str] = {
    **DEFAULT_KEYMAP,
    # vim-style stays the same as default; included so --keymap vim
    # is a stable alias users can rely on without surprise.
}


BASIC_KEYMAP: dict[str, str] = {
    # No Ctrl combos — sidesteps terminals that swallow ctrl+z.
    "g": LABEL_GOOD,
    "b": LABEL_BAD,
    "p": LABEL_PREFERENCE_PAIR,
    "s": SKIP,
    "space": TOGGLE_SELECT,
    "G": BATCH_GOOD,
    "B": BATCH_BAD,
    "enter": ACCEPT_SUGGESTION,
    "comma": GO_BACK,
    "full_stop": GO_FORWARD,
    "u": UNDO,
    "slash": OPEN_FILTER,
    "question_mark": OPEN_HELP,
    "q": QUIT,
}


_BY_NAME: dict[str, dict[str, str]] = {
    "default": DEFAULT_KEYMAP,
    "vim": VIM_KEYMAP,
    "basic": BASIC_KEYMAP,
}


def get_keymap(name: str) -> dict[str, str]:
    """Return the keymap dict for ``name``. Unknown names fall back
    to the default; the CLI restricts ``--keymap`` to the known set
    via argparse ``choices`` so this is defence-in-depth."""
    return _BY_NAME.get(name, DEFAULT_KEYMAP)


def known_keymaps() -> list[str]:
    return list(_BY_NAME)
