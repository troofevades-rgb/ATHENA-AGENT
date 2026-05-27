"""Theme system — registration, switching, and legacy
module-attribute backward compatibility."""

from __future__ import annotations

import pytest

from athena import ui


@pytest.fixture(autouse=True)
def _reset_to_default():
    ui.set_theme("phosphor")
    yield
    ui.set_theme("phosphor")


def test_phosphor_is_default():
    assert ui.theme().name == "phosphor"


def test_themes_registered():
    """Two themes: ``phosphor`` (default, CRT lime) and
    ``noctua`` (owl-family electric cyan). The 5 themes we used
    to ship (dusk, nord, dracula, synthwave, cyber) were
    removed during the UI cleanup — they added cognitive load
    without users asking for them."""
    names = {t.name for t in ui.list_themes()}
    assert names == {"phosphor", "noctua"}


def test_each_theme_has_full_palette():
    for t in ui.list_themes():
        assert t.primary.startswith("#"), f"{t.name}: bad primary"
        assert t.primary_dim.startswith("#"), f"{t.name}: bad primary_dim"
        assert t.primary_faint.startswith("#"), f"{t.name}: bad primary_faint"
        assert t.accent.startswith("#"), f"{t.name}: bad accent"
        assert t.accent_dim.startswith("#"), f"{t.name}: bad accent_dim"
        assert len(t.gradient) >= 4, f"{t.name}: gradient too short"


def test_set_theme_changes_active():
    ui.set_theme("noctua")
    assert ui.theme().name == "noctua"


def test_set_theme_unknown_raises():
    with pytest.raises(KeyError, match="unknown theme"):
        ui.set_theme("nonexistent")


def test_set_theme_returns_new_theme():
    returned = ui.set_theme("noctua")
    assert returned is ui.theme()
    assert returned.name == "noctua"


# ----- legacy module-level attributes (LIME, etc.) -----
#
# Some pre-cleanup code still reads ``ui.LIME`` etc. by name.
# These rebind in ``set_theme`` so f-string consumers see the
# active palette. Tests pin that the rebinds happen.


def test_lime_tracks_active_theme():
    ui.set_theme("phosphor")
    assert ui.LIME == "#00ff00"
    ui.set_theme("noctua")
    assert ui.LIME == "#43e8ff"


def test_lime_dim_tracks_active_theme():
    ui.set_theme("phosphor")
    phos = ui.LIME_DIM
    ui.set_theme("noctua")
    assert ui.LIME_DIM != phos


def test_gradient_tracks_active_theme():
    ui.set_theme("phosphor")
    g1 = tuple(ui._GRADIENT)
    ui.set_theme("noctua")
    g2 = tuple(ui._GRADIENT)
    assert g1 != g2


def test_owl_accent_tracks_active_theme():
    ui.set_theme("phosphor")
    a1 = ui._OWL_AMBER
    ui.set_theme("noctua")
    a2 = ui._OWL_AMBER
    assert a1 != a2
