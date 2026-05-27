"""Tests for ``/resume [file]`` — load a saved session transcript."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from athena.commands.resume import cmd_resume


def _capture():
    lines: list[str] = []
    patches = []
    for fn in ("info", "warn", "error"):
        patches.append(
            patch(
                f"athena.commands.resume.ui.{fn}",
                side_effect=lambda msg, *a, _n=fn, **kw:
                    lines.append(f"{_n}: {msg}"),
            )
        )
    patches.append(
        patch(
            "athena.commands.resume.ui.console.print",
            side_effect=lambda *a, **kw:
                lines.append(" ".join(str(x) for x in a)),
        )
    )
    return lines, patches


def _run(agent, arg: str) -> str:
    lines, patches = _capture()
    for p in patches:
        p.start()
    try:
        cmd_resume(agent, arg)
    finally:
        for p in patches:
            p.stop()
    return "\n".join(lines)


def _agent_with_system(initial_system: str = "you are athena"):
    return SimpleNamespace(
        messages=[{"role": "system", "content": initial_system}],
    )


@pytest.fixture
def fake_sessions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Replace SESSIONS_DIR with a tmp_path so list + load can't reach
    the real ~/.athena/sessions."""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    monkeypatch.setattr("athena.commands.resume.SESSIONS_DIR", sessions)
    return sessions


# ---- no arg: list recent sessions -----------------------------------


def test_no_arg_with_empty_dir_says_no_sessions(
    fake_sessions_dir: Path,
) -> None:
    out = _run(_agent_with_system(), "")
    assert "no sessions" in out.lower()
    assert str(fake_sessions_dir) in out


def test_no_arg_lists_recent_sessions(fake_sessions_dir: Path) -> None:
    """Populate three session files; the listing must show all of
    them in newest-first order."""
    import time
    paths = []
    for i, name in enumerate(["oldest.json", "middle.json", "newest.json"]):
        p = fake_sessions_dir / name
        p.write_text(json.dumps([{"role": "user", "content": str(i)}]))
        # Stagger mtimes so newest sorts first deterministically.
        ts = 1000 + i * 100
        import os
        os.utime(p, (ts, ts))
        paths.append(p)
    out = _run(_agent_with_system(), "")
    # All three filenames appear
    for p in paths:
        assert p.name in out
    # Newest first
    assert out.index("newest.json") < out.index("middle.json") < out.index("oldest.json")


def test_no_arg_caps_listing_at_10(fake_sessions_dir: Path) -> None:
    """Listing must not flood the screen with hundreds of sessions."""
    for i in range(20):
        (fake_sessions_dir / f"s{i:03d}.json").write_text("[]")
    out = _run(_agent_with_system(), "")
    visible = sum(1 for ln in out.splitlines() if ".json" in ln)
    assert visible == 10


# ---- arg: load a specific session -----------------------------------


def test_load_absolute_path_replaces_history(
    fake_sessions_dir: Path, tmp_path: Path
) -> None:
    """Saved messages should replace the agent's history EXCEPT the
    original system prompt (which must be preserved)."""
    saved = tmp_path / "saved.json"
    saved.write_text(json.dumps([
        {"role": "system", "content": "OLD system prompt — must be dropped"},
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
    ]))
    agent = _agent_with_system("KEEP THIS SYSTEM PROMPT")
    out = _run(agent, str(saved))
    # Agent's original system prompt preserved
    assert agent.messages[0] == {
        "role": "system", "content": "KEEP THIS SYSTEM PROMPT",
    }
    # Saved system prompt was dropped
    assert all("OLD system prompt" not in m.get("content", "") for m in agent.messages)
    # Saved user + assistant messages copied
    assert agent.messages[1] == {"role": "user", "content": "previous question"}
    assert agent.messages[2] == {"role": "assistant", "content": "previous answer"}
    # User-visible confirmation
    assert "resumed" in out.lower()
    assert "2 messages" in out


def test_load_bare_filename_resolves_against_sessions_dir(
    fake_sessions_dir: Path,
) -> None:
    """``/resume foo.json`` should find it in SESSIONS_DIR even when
    the cwd is unrelated."""
    target = fake_sessions_dir / "abc.json"
    target.write_text(json.dumps([{"role": "user", "content": "ok"}]))
    agent = _agent_with_system()
    _run(agent, "abc.json")
    assert agent.messages[1] == {"role": "user", "content": "ok"}


def test_load_nonexistent_file_errors(fake_sessions_dir: Path) -> None:
    agent = _agent_with_system()
    out = _run(agent, "does-not-exist.json")
    assert "not found" in out.lower()
    # History unchanged
    assert len(agent.messages) == 1


def test_load_malformed_json_errors(
    fake_sessions_dir: Path, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json")
    agent = _agent_with_system()
    out = _run(agent, str(bad))
    assert "failed to load" in out.lower()
    # History unchanged
    assert len(agent.messages) == 1


def test_load_non_list_json_errors(
    fake_sessions_dir: Path, tmp_path: Path
) -> None:
    """File parses as JSON but is a dict, not a list — refuse."""
    bad = tmp_path / "wrong-shape.json"
    bad.write_text(json.dumps({"role": "user", "content": "single message dict"}))
    agent = _agent_with_system()
    out = _run(agent, str(bad))
    assert "not a list" in out.lower()
    assert len(agent.messages) == 1
