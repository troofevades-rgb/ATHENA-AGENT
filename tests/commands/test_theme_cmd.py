"""``/theme`` slash command — show / list / set / save.

Now that the theme catalog is just ``phosphor`` and ``noctua``,
the listing and switching tests only need to verify both names
show up, the switch works, and ``save`` persists correctly.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from athena import ui
from athena.commands.theme import cmd_theme


@pytest.fixture(autouse=True)
def _restore_default_theme():
    ui.set_theme("phosphor")
    yield
    ui.set_theme("phosphor")


def _capture_ui():
    lines: list[str] = []
    patches = []
    for fn_name in ("info", "warn", "error"):
        patches.append(
            patch(
                f"athena.commands.theme.ui.{fn_name}",
                side_effect=lambda msg, *a, _n=fn_name, **kw:
                    lines.append(f"{_n}: {msg}"),
            )
        )
    patches.append(
        patch(
            "athena.commands.theme.ui.console.print",
            side_effect=lambda *a, **kw:
                lines.append(" ".join(str(x) for x in a)),
        )
    )
    return lines, patches


def _run(arg: str = ""):
    lines, patches = _capture_ui()
    for p in patches:
        p.start()
    try:
        result = cmd_theme(SimpleNamespace(), arg)
    finally:
        for p in patches:
            p.stop()
    return result, "\n".join(lines)


def test_status_shows_both_themes():
    _, out = _run("")
    assert "phosphor" in out
    assert "noctua" in out


def test_status_marks_active_with_asterisk():
    ui.set_theme("noctua")
    _, out = _run("")
    list_lines = [
        l for l in out.splitlines() if "active theme" not in l.lower()
    ]
    noctua_line = next(l for l in list_lines if "noctua" in l)
    phos_line = next(l for l in list_lines if "phosphor" in l)
    assert "*" in noctua_line
    assert "*" not in phos_line


def test_list_emits_names_only():
    _, out = _run("list")
    lines = [l for l in out.splitlines() if l.strip()]
    assert set(lines) == {"phosphor", "noctua"}


def test_set_changes_active():
    _, out = _run("set noctua")
    assert ui.theme().name == "noctua"
    assert "noctua" in out.lower()


def test_set_unknown_errors():
    _, out = _run("set bogus")
    assert ui.theme().name == "phosphor"  # unchanged
    assert "unknown" in out.lower()


def test_set_with_no_arg_errors():
    _, out = _run("set")
    assert "usage" in out.lower()


def test_unknown_subcommand_errors():
    _, out = _run("frobnicate")
    assert "unknown" in out.lower()


def test_save_writes_theme_line(tmp_path, monkeypatch):
    """``/theme save`` persists the active theme above any
    section header. The TOML-placement gotcha we hit twice in
    this thread must be honored here too."""
    fake_home = tmp_path
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    cfg_path = fake_home / ".athena" / "config.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        'model = "x"\n\n[gateway.platforms.discord]\nenabled = true\n',
        encoding="utf-8",
    )

    ui.set_theme("noctua")
    _run("save")
    text = cfg_path.read_text(encoding="utf-8")
    assert 'theme = "noctua"' in text
    theme_idx = text.index("theme = ")
    section_idx = text.index("[gateway")
    assert theme_idx < section_idx, (
        "theme= line landed below [gateway] section — would parse as "
        "cfg.gateway.platforms.discord.theme, not cfg.theme"
    )


def test_save_creates_config_when_missing(tmp_path, monkeypatch):
    fake_home = tmp_path
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    cfg_path = fake_home / ".athena" / "config.toml"
    assert not cfg_path.exists()

    ui.set_theme("noctua")
    _run("save")
    assert cfg_path.exists()
    assert 'theme = "noctua"' in cfg_path.read_text(encoding="utf-8")


def test_save_replaces_existing_theme_line(tmp_path, monkeypatch):
    fake_home = tmp_path
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    cfg_path = fake_home / ".athena" / "config.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        'theme = "phosphor"\nmodel = "x"\n', encoding="utf-8",
    )

    ui.set_theme("noctua")
    _run("save")
    text = cfg_path.read_text(encoding="utf-8")
    assert text.count("theme = ") == 1
    assert 'theme = "noctua"' in text
    assert 'theme = "phosphor"' not in text
