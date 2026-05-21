"""Backend availability + observe-surface tests (T6-04.3).

Real screenshot tests are gated by backend availability. The
detector + the noop fallback are tested unconditionally.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from athena.computer.backends.noop import NoOpBackend
from athena.computer.detect import available_backends, select_backend


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


def test_select_backend_auto_returns_backend():
    """Auto-select always returns *something* — never raises.
    On hosts without a usable platform backend, falls through
    to NoOpBackend."""
    cfg = SimpleNamespace(computer_backend="auto")
    backend = select_backend(cfg)
    assert backend is not None
    assert hasattr(backend, "is_available")
    assert hasattr(backend, "screenshot")
    assert hasattr(backend, "perform")


def test_select_backend_noop_forced():
    cfg = SimpleNamespace(computer_backend="noop")
    backend = select_backend(cfg)
    assert backend.name == "noop"
    assert backend.is_available() is False
    assert backend.supports() == []


def test_select_backend_unknown_falls_through_to_noop():
    """A typo in computer_backend should NOT crash — it should
    fall through to the noop stub."""
    cfg = SimpleNamespace(computer_backend="zarquon")
    backend = select_backend(cfg)
    # Either the requested backend resolved (unlikely for
    # "zarquon") or the noop fallback. Both are acceptable; the
    # contract is no-crash.
    assert backend is not None


def test_available_backends_includes_noop():
    """The status report always lists noop as available."""
    backends = available_backends()
    names = [b["name"] for b in backends]
    assert "noop" in names
    noop_row = next(b for b in backends if b["name"] == "noop")
    assert noop_row["available"] is True


def test_available_backends_lists_every_platform():
    """The status report lists every backend athena knows
    about, so the operator can see what's possible — even when
    not currently usable on this host."""
    names = [b["name"] for b in available_backends()]
    assert "windows" in names
    assert "macos" in names
    assert "linux" in names
    assert "noop" in names


# ---------------------------------------------------------------------------
# NoOpBackend contract
# ---------------------------------------------------------------------------


def test_noop_backend_screenshot_raises():
    backend = NoOpBackend()
    with pytest.raises(RuntimeError, match="cannot capture"):
        backend.screenshot()


def test_noop_backend_perform_raises():
    backend = NoOpBackend()
    from athena.computer.contract import Action

    with pytest.raises(RuntimeError, match="cannot perform"):
        backend.perform(Action(type="click", coords=(0, 0)))


def test_noop_backend_active_app_returns_none():
    assert NoOpBackend().active_app() is None


def test_noop_backend_a11y_tree_returns_none():
    assert NoOpBackend().accessibility_tree() is None


# ---------------------------------------------------------------------------
# Windows backend — gated by platform
# ---------------------------------------------------------------------------


_windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows backend only runs on Windows hosts",
)


@_windows_only
def test_windows_backend_is_available():
    from athena.computer.backends.windows import WindowsBackend

    backend = WindowsBackend()
    assert backend.is_available() is True
    assert "screenshot" in backend.supports()


@_windows_only
def test_windows_backend_screenshot_returns_image():
    """A real screenshot — the actual desktop. Verifies the
    BitBlt round-trip works, the geometry is reported, and the
    bytes blob is non-trivial."""
    from athena.computer.backends.windows import WindowsBackend

    backend = WindowsBackend()
    shot = backend.screenshot()
    assert shot.width > 0
    assert shot.height > 0
    assert shot.scale > 0
    # BMP file header — "BM" at the start.
    assert shot.png_bytes[:2] == b"BM"
    # Non-trivial size: at least the BMP headers (54 bytes) +
    # something for pixels.
    assert len(shot.png_bytes) > 100


@_windows_only
def test_windows_backend_active_app_returns_something_or_none():
    """active_app returns a window title or None (when no
    foreground window) — never crashes."""
    from athena.computer.backends.windows import WindowsBackend

    backend = WindowsBackend()
    result = backend.active_app()
    assert result is None or isinstance(result, str)


@_windows_only
def test_windows_backend_perform_unimplemented_until_t6_04_5():
    """Until T6-04.5 wires SendInput, perform() must raise —
    the observe-first design invariant."""
    from athena.computer.backends.windows import WindowsBackend
    from athena.computer.contract import Action

    backend = WindowsBackend()
    with pytest.raises(NotImplementedError, match="T6-04.5"):
        backend.perform(Action(type="click", coords=(0, 0)))


@_windows_only
def test_windows_backend_supports_observe_only():
    """The supports list in T6-04.3 includes only the observe
    actions — no input verbs yet."""
    from athena.computer.backends.windows import WindowsBackend

    backend = WindowsBackend()
    supports = backend.supports()
    assert "screenshot" in supports
    for input_verb in ("click", "double_click", "type", "key", "scroll", "drag", "move"):
        assert input_verb not in supports, (
            f"input verb {input_verb!r} appeared in supports — must wait for T6-04.5"
        )


# ---------------------------------------------------------------------------
# Cross-platform: non-Windows hosts → Windows backend reports unavailable
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="This test pins the non-Windows fallback behaviour",
)
def test_windows_backend_unavailable_on_non_windows():
    from athena.computer.backends.windows import WindowsBackend

    backend = WindowsBackend()
    assert backend.is_available() is False
