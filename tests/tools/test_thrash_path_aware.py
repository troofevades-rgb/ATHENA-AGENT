"""Path-aware arg hashing in thrash detection.

The model wanders through equivalent paths spelled different ways —
``/c/Users/foo``, ``C:\\Users\\foo``, ``~/foo`` (when home is
``C:\\Users``), ``./foo`` from the workspace. Without normalization
each call hashes differently and the loop never trips. These tests
verify that path-shaped argument values are canonicalized before
hashing so semantically-equal calls do collide.
"""

from __future__ import annotations

import sys

import pytest

from athena.tools import thrash


@pytest.fixture(autouse=True)
def _reset_thrash():
    thrash.reset()
    yield
    thrash.reset()


def test_path_keys_canonicalize_before_hashing(tmp_path, monkeypatch):
    """Two list_dir calls with the same target spelled differently
    hash to the same key — third identical call trips the warning."""
    from athena.tools import file_ops

    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)

    # Both forms resolve to the same path (cwd-relative vs absolute).
    target = tmp_path / "sub"
    target.mkdir()

    args_abs = {"path": str(target)}
    args_rel = {"path": "sub"}

    # Same canonical form → same hash.
    assert thrash._hash_args(args_abs) == thrash._hash_args(args_rel)


def test_non_path_key_not_canonicalized(tmp_path, monkeypatch):
    """A path-looking value under a non-path key (e.g. `description`)
    must not be normalized — that would collapse legitimate variation."""
    from athena.tools import file_ops

    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)

    a = {"description": "see ~/foo"}
    b = {"description": "see /c/Users/mtt_j/foo"}
    # Same prose intent but different strings → different hash.
    assert thrash._hash_args(a) != thrash._hash_args(b)


def test_msys_and_windows_paths_collide_on_windows(monkeypatch, tmp_path):
    """On Windows, /c/Users/X and C:\\Users\\X are the same place."""
    if sys.platform != "win32":
        pytest.skip("MSYS collision only meaningful on Windows")

    from athena.tools import file_ops

    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)

    # Construct two spellings of the same path.
    win = str(tmp_path)  # C:\Users\runner\AppData\...\tmpXYZ
    drive_letter = win[0].lower()
    rest = win[2:].replace("\\", "/")
    msys = f"/{drive_letter}{rest}"

    assert thrash._hash_args({"path": win}) == thrash._hash_args({"path": msys})


def test_three_semantically_equal_calls_trip_warning(tmp_path, monkeypatch):
    """Regression test for the exact failure mode in the user's
    transcript — model bounces between equivalent path spellings,
    each call hashing differently. With canonical hashing, the third
    semantically-equal call short-circuits."""
    from athena.tools import file_ops

    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)

    sub = tmp_path / "sub"
    sub.mkdir()

    # Three different spellings of the same destination.
    spellings = [str(sub), "sub", "./sub"]
    # Pretend each call returned the same listing.
    for s in spellings[:2]:
        thrash.record("list_dir", {"path": s}, "file_a\nfile_b\n")

    # The third with yet another spelling should now trip.
    warning = thrash.precheck("list_dir", {"path": spellings[2]})
    assert warning is not None
    assert "THRASH WARNING" in warning


def test_empty_path_value_passes_through(tmp_path, monkeypatch):
    """Empty string under a path key shouldn't crash normalization."""
    from athena.tools import file_ops

    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)

    # Just call _hash_args; no assertion needed beyond "doesn't raise".
    h = thrash._hash_args({"path": ""})
    assert isinstance(h, str)


def test_non_string_path_value_passes_through(tmp_path, monkeypatch):
    """If the model passes a non-string under a path key, we don't
    normalize — we hash the dict as-is."""
    from athena.tools import file_ops

    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)

    h = thrash._hash_args({"path": 42})
    assert isinstance(h, str)
