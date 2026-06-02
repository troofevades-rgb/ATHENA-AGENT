"""``/godmode`` follow-ups -- skill-path resolution, parseltongue arg
parsing, and the /clear interaction.

Round 1 of the wire-up (commit ccc6d50) made the six broken
subcommands functional. This file pins the second round of
fixes:

  * **Skill path discovery (A + F)** -- ``_get_skill_path(agent)``
    now also checks ``<agent.workspace>/.athena/skills/godmode/``
    so the in-repo bundled skill works without a global install.
    The old cwd fallback (``Path.cwd() / "skills" / "godmode"``)
    was wrong-shaped (the repo uses ``.athena/skills/godmode/``,
    not ``skills/godmode/``) and is removed.
  * **/clear drops _active_godmode and drains steers (B + C)** --
    ``Agent.reset()`` historically wiped ``messages`` and
    ``stats`` but not the godmode marker, so ``/godmode list``
    would render ``(active)`` after ``/clear`` despite the steer
    that carried the jailbreak being gone. Same code path also
    drains the per-session steer queue so a steer pushed before
    ``/clear`` doesn't fire on the next prompt.
  * **Parseltongue arg parsing (D)** -- replaced the brittle
    ``rest.replace(f"--tier {tier}", "")`` one-liner with a small
    tokenizer that handles ``--tier X``, ``--tier=X``, trailing
    ``--tier`` (no value), flag before query, multiple flags
    (last wins), and an empty rest.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures matching the wire-up tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_dotenv(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
):
    import athena.env as env_mod

    fake = tmp_path_factory.mktemp("dotenv_iso") / "missing.env"
    monkeypatch.setattr(env_mod, "_path", lambda: fake)
    env_mod.reset_cache()
    yield
    env_mod.reset_cache()


@pytest.fixture
def _gate_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATHENA_ALLOW_GODMODE", "1")


@pytest.fixture
def _captured_ui(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    import athena.commands.godmode as gm

    buckets: dict[str, list[str]] = {
        "warn": [],
        "error": [],
        "info": [],
        "print": [],
    }

    def _record(bucket: str):
        def _capture(msg: Any = "", *_a: Any, **_kw: Any) -> None:
            buckets[bucket].append(str(msg))

        return _capture

    monkeypatch.setattr(gm.ui, "warn", _record("warn"))
    monkeypatch.setattr(gm.ui, "error", _record("error"))
    monkeypatch.setattr(gm.ui, "info", _record("info"))
    monkeypatch.setattr(gm.ui.console, "print", _record("print"))
    return buckets


# ---------------------------------------------------------------------------
# A + F -- _get_skill_path resolution
# ---------------------------------------------------------------------------


def test_skill_path_uses_global_when_scripts_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The user-global install at ``~/.athena/skills/godmode/`` is
    the primary path. When its ``scripts/`` subdir exists,
    ``_get_skill_path`` returns it regardless of the workspace."""
    import athena.commands.godmode as gm

    global_skill = tmp_path / "global"
    (global_skill / "scripts").mkdir(parents=True)
    workspace = tmp_path / "ws"
    (workspace / ".athena" / "skills" / "godmode" / "scripts").mkdir(parents=True)

    monkeypatch.setattr(gm, "SKILL_PATH", global_skill)
    agent = SimpleNamespace(workspace=workspace)

    assert gm._get_skill_path(agent) == global_skill


def test_skill_path_falls_back_to_workspace_when_global_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When the user-global install has no ``scripts/`` subdir, the
    workspace's ``.athena/skills/godmode/`` is the fallback. This
    is the load-bearing fix for the actual failure mode: parseltongue
    script lives in the repo, not in ``~/.athena``."""
    import athena.commands.godmode as gm

    global_skill = tmp_path / "global"  # no scripts/ -- not populated
    workspace = tmp_path / "ws"
    (workspace / ".athena" / "skills" / "godmode" / "scripts").mkdir(parents=True)

    monkeypatch.setattr(gm, "SKILL_PATH", global_skill)
    agent = SimpleNamespace(workspace=workspace)

    expected = workspace / ".athena" / "skills" / "godmode"
    assert gm._get_skill_path(agent) == expected


def test_skill_path_falls_back_to_global_when_neither_populated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """If neither global nor workspace has scripts/, return the
    global path so the eventual ``script.exists()`` failure points
    operators at where they should install."""
    import athena.commands.godmode as gm

    global_skill = tmp_path / "global"
    workspace = tmp_path / "ws"
    # No scripts/ in either.

    monkeypatch.setattr(gm, "SKILL_PATH", global_skill)
    agent = SimpleNamespace(workspace=workspace)

    assert gm._get_skill_path(agent) == global_skill


def test_skill_path_handles_agent_without_workspace_attr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Sub-agents and stubs may not have a ``workspace`` attribute.
    The resolver must not crash -- it falls back to the global path."""
    import athena.commands.godmode as gm

    monkeypatch.setattr(gm, "SKILL_PATH", tmp_path / "global")
    agent_no_ws = SimpleNamespace()  # no .workspace attribute

    # Must not raise; returns the SKILL_PATH default.
    assert gm._get_skill_path(agent_no_ws) == tmp_path / "global"


def test_get_templates_dir_is_removed() -> None:
    """``_get_templates_dir`` and ``TEMPLATES_DIR`` were dead code
    after the wire-up moved to inline ``TEMPLATES``. Verify the
    cleanup so a future revert is caught."""
    import athena.commands.godmode as gm

    assert not hasattr(gm, "_get_templates_dir")
    assert not hasattr(gm, "TEMPLATES_DIR")


# ---------------------------------------------------------------------------
# B + C -- Agent.reset() drops the godmode marker AND drains steers
# (those four tests live at tests/agent/test_reset_clears_session_state.py
# because they need the ``fake_provider`` fixture from tests/agent/conftest.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# D -- _parse_parseltongue_args tokenizer
# ---------------------------------------------------------------------------


def test_parse_parseltongue_default_tier_when_flag_absent() -> None:
    from athena.commands.godmode import _parse_parseltongue_args

    query, tier = _parse_parseltongue_args("encode this please")
    assert query == "encode this please"
    assert tier == "standard"


def test_parse_parseltongue_explicit_tier_with_space() -> None:
    from athena.commands.godmode import _parse_parseltongue_args

    query, tier = _parse_parseltongue_args("encode this --tier heavy")
    assert query == "encode this"
    assert tier == "heavy"


def test_parse_parseltongue_explicit_tier_with_equals() -> None:
    from athena.commands.godmode import _parse_parseltongue_args

    query, tier = _parse_parseltongue_args("encode this --tier=light")
    assert query == "encode this"
    assert tier == "light"


def test_parse_parseltongue_flag_before_query() -> None:
    """The old ``rest.replace`` couldn't handle ``--tier`` appearing
    before the query because it expected ``--tier <tier>`` to be
    contiguous with the rest. The tokenizer handles any position."""
    from athena.commands.godmode import _parse_parseltongue_args

    query, tier = _parse_parseltongue_args("--tier heavy encode this")
    assert query == "encode this"
    assert tier == "heavy"


def test_parse_parseltongue_trailing_bare_tier_silently_drops() -> None:
    """``parseltongue foo --tier`` (no value) historically left
    ``--tier`` in the query because the replace pattern
    ``"--tier standard"`` didn't match a bare ``--tier``. Now the
    tokenizer silently drops the bare flag; tier defaults to
    ``standard``."""
    from athena.commands.godmode import _parse_parseltongue_args

    query, tier = _parse_parseltongue_args("foo --tier")
    assert query == "foo"
    assert tier == "standard"


def test_parse_parseltongue_multiple_tier_last_wins() -> None:
    """Argparse semantics: a later flag overrides an earlier one."""
    from athena.commands.godmode import _parse_parseltongue_args

    query, tier = _parse_parseltongue_args("foo --tier light --tier heavy")
    assert query == "foo"
    assert tier == "heavy"


def test_parse_parseltongue_empty_rest_returns_empty_query() -> None:
    """No args at all -> empty query so the caller's
    ``if not query`` branch fires the usage error."""
    from athena.commands.godmode import _parse_parseltongue_args

    query, tier = _parse_parseltongue_args("")
    assert query == ""
    assert tier == "standard"


def test_parse_parseltongue_query_with_dashed_words_not_eaten() -> None:
    """Only ``--tier`` is treated as a flag; other dashed tokens
    pass through as part of the query."""
    from athena.commands.godmode import _parse_parseltongue_args

    query, tier = _parse_parseltongue_args("test --help me --tier light")
    assert query == "test --help me"
    assert tier == "light"


# ---------------------------------------------------------------------------
# Integration: cmd_godmode("parseltongue ...") uses the new parser
# correctly
# ---------------------------------------------------------------------------


def test_cmd_godmode_parseltongue_uses_new_parser(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """End-to-end: /godmode parseltongue with --tier=light at the
    end calls the script with --level 1 and passes the query
    cleanly (no stray ``--tier`` in the encoded input)."""
    import athena.commands.godmode as gm

    fake_skill = tmp_path / "skills" / "godmode"
    (fake_skill / "scripts").mkdir(parents=True)
    (fake_skill / "scripts" / "parseltongue.py").write_text("# mock", encoding="utf-8")
    monkeypatch.setattr(gm, "_get_skill_path", lambda _agent: fake_skill)

    captured: list[list[str]] = []

    def _fake_run(argv, **kw):
        captured.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="OK", stderr="")

    monkeypatch.setattr(gm.subprocess, "run", _fake_run)
    agent = SimpleNamespace(
        workspace=None,
        cfg=SimpleNamespace(profile="default"),
        session_id="sess-followup",
    )
    gm.cmd_godmode(agent, "parseltongue hello world --tier=light")

    argv = captured[0]
    # The query passed to --encode contains no stray "--tier".
    encode_idx = argv.index("--encode")
    query_arg = argv[encode_idx + 1]
    assert query_arg == "hello world"
    assert "--tier" not in query_arg
    # --level 1 matches light.
    level_idx = argv.index("--level")
    assert argv[level_idx + 1] == "1"
