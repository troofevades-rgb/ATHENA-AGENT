"""Tests for the Obsidian vault tools (athena/tools/obsidian.py)."""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from athena.tools import obsidian


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "MyVault"
    v.mkdir()
    cfg = types.SimpleNamespace(
        obsidian_vault_path=str(v),
        obsidian_daily_folder="Daily",
        obsidian_daily_date_format="%Y-%m-%d",
    )
    monkeypatch.setattr(obsidian, "active_cfg", lambda: cfg)
    return v


# ---- gating ----------------------------------------------------------------


def test_check_fn_false_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        obsidian, "active_cfg", lambda: types.SimpleNamespace(obsidian_vault_path=None)
    )
    assert obsidian._vault_ready() is False


def test_check_fn_true_when_vault_exists(vault: Path) -> None:
    assert obsidian._vault_ready() is True


def test_not_configured_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        obsidian, "active_cfg", lambda: types.SimpleNamespace(obsidian_vault_path=None)
    )
    out = obsidian.obsidian_write("Note", "hi")
    assert "not configured" in out.lower()


# ---- write / read ----------------------------------------------------------


def test_create_and_read(vault: Path) -> None:
    out = obsidian.obsidian_write("Ideas", "first thought")
    assert "created" in out
    assert (vault / "Ideas.md").is_file()
    read = obsidian.obsidian_read("Ideas")
    assert "first thought" in read


def test_create_fails_if_exists(vault: Path) -> None:
    obsidian.obsidian_write("Dup", "a")
    out = obsidian.obsidian_write("Dup", "b")
    assert out.startswith("ERROR")
    assert (vault / "Dup.md").read_text(encoding="utf-8").strip() == "a"


def test_overwrite(vault: Path) -> None:
    obsidian.obsidian_write("Note", "old")
    out = obsidian.obsidian_write("Note", "new", mode="overwrite")
    assert "overwrote" in out
    assert "new" in (vault / "Note.md").read_text(encoding="utf-8")


def test_write_append_mode(vault: Path) -> None:
    obsidian.obsidian_write("Log", "line one")
    obsidian.obsidian_write("Log", "line two", mode="append")
    body = (vault / "Log.md").read_text(encoding="utf-8")
    assert "line one" in body and "line two" in body


def test_frontmatter_and_tags_roundtrip(vault: Path) -> None:
    obsidian.obsidian_write(
        "Tagged",
        "body text",
        frontmatter={"status": "wip"},
        tags=["project", "athena"],
    )
    raw = (vault / "Tagged.md").read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    fm, body = obsidian._split_frontmatter(raw)
    assert fm["status"] == "wip"
    assert fm["tags"] == ["project", "athena"]
    assert "body text" in body


def test_wikilinks_and_tags_preserved(vault: Path) -> None:
    obsidian.obsidian_write("Linked", "see [[Other Note]] about #topic")
    body = (vault / "Linked.md").read_text(encoding="utf-8")
    assert "[[Other Note]]" in body
    assert "#topic" in body


def test_read_by_title_in_subfolder(vault: Path) -> None:
    obsidian.obsidian_write("Projects/Deep", "nested body")
    # Resolve by bare title even though it lives in a subfolder.
    out = obsidian.obsidian_read("Deep")
    assert "nested body" in out
    assert "Projects/Deep.md" in out


def test_read_missing(vault: Path) -> None:
    assert obsidian.obsidian_read("Nope").startswith("ERROR")


# ---- append ----------------------------------------------------------------


def test_append_creates_when_missing(vault: Path) -> None:
    out = obsidian.obsidian_append("Running", "entry 1")
    assert "created" in out
    assert "entry 1" in (vault / "Running.md").read_text(encoding="utf-8")


def test_append_under_heading(vault: Path) -> None:
    obsidian.obsidian_append("Running", "entry 1", heading="Today")
    obsidian.obsidian_append("Running", "entry 2", heading="Today")
    body = (vault / "Running.md").read_text(encoding="utf-8")
    # Heading added once; both entries present.
    assert body.count("## Today") == 1
    assert "entry 1" in body and "entry 2" in body


# ---- search ----------------------------------------------------------------


def test_search_by_content(vault: Path) -> None:
    obsidian.obsidian_write("A", "the quick brown fox")
    obsidian.obsidian_write("B", "nothing here")
    out = obsidian.obsidian_search("brown")
    assert "A.md" in out
    assert "B.md" not in out


def test_search_empty_lists_notes(vault: Path) -> None:
    obsidian.obsidian_write("A", "x")
    obsidian.obsidian_write("B", "y")
    out = obsidian.obsidian_search("")
    assert "A.md" in out and "B.md" in out


# ---- daily -----------------------------------------------------------------


def test_daily_note(vault: Path) -> None:
    from datetime import datetime

    out = obsidian.obsidian_daily("did a thing", heading="Notes")
    stamp = datetime.now().strftime("%Y-%m-%d")
    daily = vault / "Daily" / f"{stamp}.md"
    assert daily.is_file()
    assert "did a thing" in daily.read_text(encoding="utf-8")
    assert stamp in out


# ---- security --------------------------------------------------------------


def test_path_traversal_rejected(vault: Path, tmp_path: Path) -> None:
    out = obsidian.obsidian_write("../escape", "evil", mode="overwrite")
    assert out.startswith("ERROR")
    assert "escapes the vault" in out
    assert not (tmp_path / "escape.md").exists()


def test_absolute_path_does_not_escape_vault(vault: Path, tmp_path: Path) -> None:
    # An absolute path is rewritten to a vault-relative one (anchor stripped),
    # so it is contained INSIDE the vault rather than written to disk outside.
    outside = tmp_path / "outside.md"
    obsidian.obsidian_write((tmp_path / "outside").as_posix(), "evil", mode="overwrite")
    assert not outside.exists()
