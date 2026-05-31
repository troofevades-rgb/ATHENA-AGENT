"""Deprecation-warning dedup across ``load_config()`` calls.

Audit P2 follow-up. Before this dedup, ``__main__.py``'s sequence:

  load_config()  # for startup_notice
  load_config()  # for the real cfg

made every deprecated-key warning fire TWICE on every startup --
operators saw the same line repeated and the noise made the actual
WARN signal harder to notice. Now each ``(config_path, legacy_key)``
pair fires its warning at most ONCE per process.

Pins:

  * Two successive ``load_config()`` calls produce ONE warning per
    deprecated key (not two).
  * ``reset_deprecation_dedup()`` clears the state for hermetic
    tests.
  * ``reported_deprecations()`` exposes the dedup set so callers
    (``athena doctor``) can render a one-stop summary.
  * Different ``config_path`` produces independent warnings -- a
    profile-switch shouldn't silence the new path's deprecations.
  * Multiple distinct keys in the same config all warn (just not
    twice each).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from athena import config as config_mod


@pytest.fixture(autouse=True)
def _isolate_dedup_state():
    """Save / restore the module-level dedup set around every test
    so deprecation pins are independent of the order other tests
    ran (and don't pollute each other's expectations)."""
    saved = set(config_mod._DEPRECATION_WARNED)
    config_mod.reset_deprecation_dedup()
    yield
    config_mod._DEPRECATION_WARNED.clear()
    config_mod._DEPRECATION_WARNED.update(saved)


@pytest.fixture
def _tmp_config_with_deprecated_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point ``CONFIG_PATH`` at a tmp file containing a single
    deprecated key (``computer_use_enabled``). Returns the path so
    a test can point a second load at a different file."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        'computer_use_enabled = true\n',
        encoding="utf-8",
    )
    # The config module reads CONFIG_PATH at function-call time, so
    # monkeypatch lands the redirect for every load in the test.
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_file)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "SESSIONS_DIR", tmp_path / "sessions")
    return cfg_file


# ---------------------------------------------------------------------------
# Core dedup behaviour
# ---------------------------------------------------------------------------


def test_two_loads_emit_one_warning(
    _tmp_config_with_deprecated_key: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """The audit pain point: ``__main__.py`` calls ``load_config()``
    twice and the warning fires twice. After dedup, the warning
    fires exactly once across the two calls."""
    config_mod.load_config()
    config_mod.load_config()

    stderr = capsys.readouterr().err
    occurrences = stderr.count("'computer_use_enabled' is deprecated")
    assert occurrences == 1


def test_reset_re_enables_warning_emission(
    _tmp_config_with_deprecated_key: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """``reset_deprecation_dedup()`` clears the in-process state so
    a subsequent load emits the warning again. This is the seam
    tests use to assert warning emission deterministically."""
    config_mod.load_config()
    capsys.readouterr()  # drain
    config_mod.reset_deprecation_dedup()
    config_mod.load_config()

    stderr = capsys.readouterr().err
    assert "'computer_use_enabled' is deprecated" in stderr


# ---------------------------------------------------------------------------
# Public read of the dedup state
# ---------------------------------------------------------------------------


def test_reported_deprecations_returns_warned_keys(
    _tmp_config_with_deprecated_key: Path,
) -> None:
    """The public ``reported_deprecations()`` exposes the dedup
    set so callers (``athena doctor``) can render a one-stop
    summary. Empty before any load; populated after."""
    assert config_mod.reported_deprecations() == frozenset()
    config_mod.load_config()
    pairs = config_mod.reported_deprecations()
    assert len(pairs) == 1
    # Each pair is (config_path, legacy_key); the legacy_key half
    # is what callers usually want.
    legacy_keys = {legacy_key for _path, legacy_key in pairs}
    assert legacy_keys == {"computer_use_enabled"}


def test_reported_deprecations_is_immutable_view() -> None:
    """``reported_deprecations()`` returns a frozenset so callers
    can't accidentally mutate the live dedup state."""
    pairs = config_mod.reported_deprecations()
    assert isinstance(pairs, frozenset)


# ---------------------------------------------------------------------------
# Multiple distinct keys + path independence
# ---------------------------------------------------------------------------


def test_multiple_deprecated_keys_in_same_config_all_warn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Each distinct deprecated key warns once. Dedup is per-key,
    not "first deprecation only"."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        'computer_use_enabled = true\n'
        'computer_permission_mode = "observe_only"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_file)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "SESSIONS_DIR", tmp_path / "sessions")

    config_mod.load_config()
    config_mod.load_config()

    stderr = capsys.readouterr().err
    assert stderr.count("'computer_use_enabled' is deprecated") == 1
    assert stderr.count("'computer_permission_mode' is deprecated") == 1


def test_emit_deprecation_emits_only_first_time(
    capsys: pytest.CaptureFixture,
) -> None:
    """Unit pin on ``_emit_deprecation`` directly: the same
    ``(path, key)`` pair only emits the message on the first call.
    Subsequent calls are silent regardless of message body
    differences -- the dedup key is the (path, key) tuple, not the
    message text."""
    config_mod._emit_deprecation(
        Path("/etc/a.toml"), "old_key", "first message"
    )
    config_mod._emit_deprecation(
        Path("/etc/a.toml"), "old_key", "different message"
    )
    stderr = capsys.readouterr().err
    assert "first message" in stderr
    assert "different message" not in stderr


def test_emit_deprecation_independent_per_path(
    capsys: pytest.CaptureFixture,
) -> None:
    """Different config paths produce independent dedup state.
    A profile switch shouldn't silence the new config's
    deprecations because the old profile's load already warned."""
    config_mod._emit_deprecation(
        Path("/etc/a.toml"), "old_key", "from path A"
    )
    config_mod._emit_deprecation(
        Path("/etc/b.toml"), "old_key", "from path B"
    )
    stderr = capsys.readouterr().err
    assert "from path A" in stderr
    assert "from path B" in stderr


# ---------------------------------------------------------------------------
# Doctor integration -- one-stop summary
# ---------------------------------------------------------------------------


def test_doctor_deprecation_check_ok_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No deprecations -> OK."""
    from athena.cli import doctor

    config_mod.reset_deprecation_dedup()
    # Avoid having load_config() find a real config with
    # deprecated keys (the dogfood machine has one).
    monkeypatch.setattr(
        config_mod, "load_config", lambda: None
    )
    # Re-import in doctor's namespace too.
    with patch(
        "athena.config.reported_deprecations",
        return_value=frozenset(),
    ):
        result = doctor._check_deprecated_config_keys()
    assert result.severity == "ok"
    assert result.detail == "none"


def test_doctor_deprecation_check_warn_with_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One or more deprecations -> WARN with the full sorted list
    so operators can fix everything in one pass instead of waiting
    for the next per-key warning."""
    from athena.cli import doctor

    monkeypatch.setattr(config_mod, "load_config", lambda: None)
    with patch(
        "athena.config.reported_deprecations",
        return_value=frozenset(
            {
                (Path("/p"), "old_a"),
                (Path("/p"), "old_b"),
                (Path("/p"), "old_c"),
            }
        ),
    ):
        result = doctor._check_deprecated_config_keys()
    assert result.severity == "warn"
    assert "3 key" in result.detail
    # Sorted order so the rendered detail is stable across runs.
    assert "old_a" in result.detail
    assert "old_b" in result.detail
    assert "old_c" in result.detail
    # extra carries the structured list for JSON consumers.
    assert result.extra["keys"] == ["old_a", "old_b", "old_c"]
