"""Tests for ``/save [path]`` — write transcript history to JSON."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from athena.commands.save import cmd_save


@pytest.fixture
def fake_agent() -> SimpleNamespace:
    """An agent with a small transcript in messages[]."""
    return SimpleNamespace(
        messages=[
            {"role": "system", "content": "You are athena."},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello back"},
        ],
    )


def _captured_info() -> tuple[list[str], list]:
    """Patch ui.info on save_cmd so we can read the saved-path message."""
    lines: list[str] = []
    patches = [
        patch(
            "athena.commands.save.ui.info",
            side_effect=lambda msg, *a, **kw: lines.append(msg),
        ),
    ]
    return lines, patches


def _run(agent, arg: str) -> str:
    lines, patches = _captured_info()
    for p in patches:
        p.start()
    try:
        cmd_save(agent, arg)
    finally:
        for p in patches:
            p.stop()
    return "\n".join(lines)


# ---- explicit path --------------------------------------------------


def test_save_writes_to_explicit_path(
    fake_agent: SimpleNamespace, tmp_path: Path
) -> None:
    target = tmp_path / "out" / "snapshot.json"
    _run(fake_agent, str(target))
    assert target.exists()
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written == fake_agent.messages


def test_save_creates_parent_directories(
    fake_agent: SimpleNamespace, tmp_path: Path
) -> None:
    """Nested target paths should auto-create parent dirs so users
    can use scratch paths without mkdir gymnastics."""
    target = tmp_path / "deeply" / "nested" / "path" / "session.json"
    assert not target.parent.exists()
    _run(fake_agent, str(target))
    assert target.exists()


def test_save_uses_indented_json(
    fake_agent: SimpleNamespace, tmp_path: Path
) -> None:
    """Pretty-printed output is the user-facing contract — humans
    read these files, so don't regress to one-line JSON."""
    target = tmp_path / "out.json"
    _run(fake_agent, str(target))
    text = target.read_text(encoding="utf-8")
    assert "\n" in text  # not all on one line
    assert text.startswith("[")  # JSON array of messages


def test_save_emits_friendly_path_message(
    fake_agent: SimpleNamespace, tmp_path: Path
) -> None:
    target = tmp_path / "snap.json"
    out = _run(fake_agent, str(target))
    assert "saved" in out.lower()
    assert str(target) in out


# ---- default path ---------------------------------------------------


def test_save_with_no_arg_uses_sessions_dir(
    fake_agent: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No arg → write under SESSIONS_DIR with a timestamp filename.
    Test patches SESSIONS_DIR to a tmp_path so we don't pollute the
    real ~/.athena/sessions."""
    monkeypatch.setattr(
        "athena.commands.save.SESSIONS_DIR", tmp_path / "sessions",
    )
    out = _run(fake_agent, "")
    # Exactly one file written into the sessions dir.
    written = list((tmp_path / "sessions").iterdir())
    assert len(written) == 1
    assert written[0].suffix == ".json"
    # And the path appears in the info() output.
    assert str(written[0]) in out


def test_save_expands_user_homedir(
    fake_agent: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``~/`` paths should expand to the user's home, not write a
    literal '~' directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
    _run(fake_agent, "~/manual.json")
    expanded = tmp_path / "manual.json"
    assert expanded.exists()


# ---- content correctness --------------------------------------------


def test_save_preserves_messages_round_trip(
    fake_agent: SimpleNamespace, tmp_path: Path
) -> None:
    """The written file must round-trip to the same list[dict]
    via json.loads — locks the contract /resume relies on."""
    target = tmp_path / "rt.json"
    _run(fake_agent, str(target))
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == fake_agent.messages


def test_save_writes_unicode_correctly(
    tmp_path: Path
) -> None:
    """Tool output frequently contains non-ASCII; UTF-8 must be
    preserved exactly (no escape sequences in the saved JSON)."""
    agent = SimpleNamespace(
        messages=[{"role": "user", "content": "owl 🦉 emoji + 中文"}],
    )
    target = tmp_path / "uni.json"
    _run(agent, str(target))
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded[0]["content"] == "owl 🦉 emoji + 中文"
