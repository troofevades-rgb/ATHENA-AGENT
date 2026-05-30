"""``/godmode`` subcommand wire-up: apply / clear / save / load / test /
parseltongue, plus the ``(active)`` marker in ``list``.

Until 0.3.0, every subcommand below ``list`` was a half-built stub --
``apply`` would have raised ImportError on a nonexistent
``athena.commands.steer._steer``; ``clear`` was a print-only no-op;
``save`` wrote ``{"strategy": "unknown", "saved_at": "now"}`` (literal
string); ``load`` printed the placeholder without applying anything;
``test`` previewed 100 chars and lied about being a test;
``parseltongue`` was a TODO with a UI.

This file pins the actually-functional wire-up:

  * ``apply`` pushes the strategy template onto
    ``GLOBAL_STEER_QUEUE`` for ``agent.session_id`` AND sets
    ``agent._active_godmode = {"strategy", "applied_at"}``.
  * ``clear`` pushes a counter-steer message AND drops
    ``_active_godmode``.
  * ``list`` marks the active strategy with ``(active)``.
  * ``save`` refuses with no active strategy; otherwise writes a
    JSON config with the strategy name + real ISO timestamps.
  * ``load`` reads the JSON, re-validates against ``TEMPLATES``,
    and routes through ``apply`` (so the steer-push + active-mark
    invariants hold for loaded configs too).
  * ``test`` is a preview that does NOT mutate session state and
    does NOT fire model calls (a "real" test would corrupt
    history N times).
  * ``parseltongue`` invokes the bundled script via subprocess
    with the tier->level mapping (light=1, standard=2, heavy=3).

The gate ``ATHENA_ALLOW_GODMODE=1`` is set in every wire-up test
(via the ``_gate_open`` fixture); gate refusal behavior is pinned
separately in ``test_godmode_gate.py``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _isolate_dotenv(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
):
    """Match the dotenv-isolation pattern from test_godmode_gate.py
    so a real ``~/.athena/.env`` can't pollute these wire-up tests
    (e.g. by silently opening the gate from disk and then losing
    it again on cache reset)."""
    import athena.env as env_mod

    fake = tmp_path_factory.mktemp("dotenv_iso") / "missing.env"
    monkeypatch.setattr(env_mod, "_path", lambda: fake)
    env_mod.reset_cache()
    yield
    env_mod.reset_cache()


@pytest.fixture
def _gate_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Open the runtime gate for every test in this file. The gate
    is what these tests are NOT about -- they exercise the body."""
    monkeypatch.setenv("ATHENA_ALLOW_GODMODE", "1")


@pytest.fixture
def _agent() -> SimpleNamespace:
    """Stub agent with a session_id so the steer queue accepts
    pushes under a real key."""
    return SimpleNamespace(
        workspace=None,
        cfg=SimpleNamespace(profile="default"),
        session_id="sess-test-1",
    )


@pytest.fixture(autouse=True)
def _clean_steer_queue() -> None:
    """Drain the module-level GLOBAL_STEER_QUEUE around every test
    so pushes from one test can't leak into another. Cleanup runs
    even on failure."""
    from athena.steer.queue import GLOBAL_STEER_QUEUE

    GLOBAL_STEER_QUEUE.clear("sess-test-1")
    GLOBAL_STEER_QUEUE.clear("_godmode_orphan")
    yield
    GLOBAL_STEER_QUEUE.clear("sess-test-1")
    GLOBAL_STEER_QUEUE.clear("_godmode_orphan")


@pytest.fixture
def _captured_ui(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Capture every ui.* call to its own bucket so a single assertion
    can inspect just the channel it cares about (warn for active-path
    reminders, info for status lines, error for failures, print for
    console output like the listing/preview blocks)."""
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
# apply -- pushes steer, sets active marker
# ---------------------------------------------------------------------------


def test_apply_pushes_template_as_steer(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """``apply og_godmode`` must push the og_godmode template into
    ``GLOBAL_STEER_QUEUE`` under the agent's session_id. The agent's
    next turn will drain it and inject as ``[/steer] <template>``."""
    from athena.commands.godmode import TEMPLATES, cmd_godmode
    from athena.steer.queue import GLOBAL_STEER_QUEUE

    cmd_godmode(_agent, "apply og_godmode")
    pending = GLOBAL_STEER_QUEUE.list("sess-test-1")
    assert len(pending) == 1
    assert pending[0] == TEMPLATES["og_godmode"]


def test_apply_marks_active_on_agent(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """The strategy name lands in ``agent._active_godmode`` so
    ``list`` can render the marker and ``save`` has something
    concrete to persist."""
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "apply refusal_inversion")
    active = getattr(_agent, "_active_godmode", None)
    assert active is not None
    assert active["strategy"] == "refusal_inversion"
    # Timestamp is real ISO-8601, not the placeholder string "now".
    from datetime import datetime

    parsed = datetime.fromisoformat(active["applied_at"])
    assert parsed.tzinfo is not None  # UTC-aware


def test_apply_unknown_strategy_errors_no_push(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """An unknown strategy must NOT push to the steer queue and
    must NOT set the active marker. The operator gets an error
    pointing at the available names."""
    from athena.commands.godmode import cmd_godmode
    from athena.steer.queue import GLOBAL_STEER_QUEUE

    cmd_godmode(_agent, "apply no_such_strategy")
    assert _captured_ui["error"]
    assert any("no_such_strategy" in m for m in _captured_ui["error"])
    assert GLOBAL_STEER_QUEUE.list("sess-test-1") == []
    assert getattr(_agent, "_active_godmode", None) is None


# ---------------------------------------------------------------------------
# clear -- pushes counter-steer, drops active marker
# ---------------------------------------------------------------------------


def test_clear_with_no_active_is_noop_no_push(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """Without an active strategy, clear is a no-op: no counter-steer
    pushed, ui.info explains there's nothing to clear."""
    from athena.commands.godmode import cmd_godmode
    from athena.steer.queue import GLOBAL_STEER_QUEUE

    cmd_godmode(_agent, "clear")
    assert GLOBAL_STEER_QUEUE.list("sess-test-1") == []
    assert any("no active" in m.lower() for m in _captured_ui["info"])


def test_clear_pushes_counter_steer_and_drops_marker(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """After apply -> clear, the steer queue contains the original
    template AND a counter-steer in FIFO order, and the active
    marker is None. The counter-steer mentions disregarding prior
    instructions so the operator can grep history for it."""
    from athena.commands.godmode import cmd_godmode
    from athena.steer.queue import GLOBAL_STEER_QUEUE

    cmd_godmode(_agent, "apply og_godmode")
    cmd_godmode(_agent, "clear")

    pending = GLOBAL_STEER_QUEUE.list("sess-test-1")
    assert len(pending) == 2
    # Original strategy was pushed first; counter-steer last.
    assert "GODMODE" in pending[0]
    assert "disregard" in pending[1].lower()
    assert "default behavior" in pending[1].lower()
    # Active marker is gone.
    assert getattr(_agent, "_active_godmode", None) is None


# ---------------------------------------------------------------------------
# list -- shows (active) marker
# ---------------------------------------------------------------------------


def test_list_shows_active_marker(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """After apply, ``list`` renders the active strategy with an
    ``(active)`` marker so the operator sees live state at a glance."""
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "apply boundary_inversion")
    _captured_ui["print"].clear()  # drop the apply chatter
    cmd_godmode(_agent, "list")

    combined = " ".join(_captured_ui["print"])
    # The active line has the marker; the others don't.
    assert "boundary_inversion" in combined
    assert "(active)" in combined
    # Sanity: non-active strategies don't get the marker. Pick one
    # known not to be active.
    lines = combined.split("\n") if "\n" in combined else _captured_ui["print"]
    og_lines = [line for line in lines if "og_godmode" in line]
    assert og_lines, "og_godmode missing from listing"
    assert not any("(active)" in line for line in og_lines)


def test_list_no_active_no_marker(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """A fresh session has no active strategy -- the listing must
    NOT show ``(active)`` anywhere."""
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "list")
    combined = " ".join(_captured_ui["print"])
    assert "(active)" not in combined


# ---------------------------------------------------------------------------
# save / load -- JSON roundtrip on the active strategy
# ---------------------------------------------------------------------------


def test_save_refuses_with_no_active(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``save mycfg`` with nothing active must error -- saving an
    empty config would just confuse ``load`` later."""
    import athena.commands.godmode as gm

    monkeypatch.setattr(gm, "CONFIG_DIR", tmp_path / "configs")
    gm.cmd_godmode(_agent, "save mycfg")
    assert _captured_ui["error"]
    assert any("no active" in m.lower() for m in _captured_ui["error"])
    assert not (tmp_path / "configs" / "mycfg.json").exists()


def test_save_then_load_roundtrips_strategy(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """apply -> save -> clear -> load yields the same active
    strategy. The JSON has the strategy name + a real ISO
    ``saved_at`` timestamp (not the literal placeholder "now")."""
    import athena.commands.godmode as gm

    monkeypatch.setattr(gm, "CONFIG_DIR", tmp_path / "configs")

    gm.cmd_godmode(_agent, "apply refusal_inversion")
    gm.cmd_godmode(_agent, "save mycfg")

    config_file = tmp_path / "configs" / "mycfg.json"
    assert config_file.exists()
    payload = json.loads(config_file.read_text(encoding="utf-8"))
    assert payload["strategy"] == "refusal_inversion"
    assert payload["name"] == "mycfg"
    # Real ISO timestamp -- the literal "now" was the pre-wireup bug.
    assert "T" in payload["saved_at"]
    assert payload["saved_at"] != "now"

    # Roundtrip: clear, then load -- strategy comes back as active.
    gm.cmd_godmode(_agent, "clear")
    assert getattr(_agent, "_active_godmode", None) is None

    gm.cmd_godmode(_agent, "load mycfg")
    active = getattr(_agent, "_active_godmode", None)
    assert active is not None
    assert active["strategy"] == "refusal_inversion"


def test_load_missing_file_errors(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import athena.commands.godmode as gm

    monkeypatch.setattr(gm, "CONFIG_DIR", tmp_path / "configs")
    gm.cmd_godmode(_agent, "load no_such_cfg")
    assert _captured_ui["error"]
    assert any("not found" in m.lower() for m in _captured_ui["error"])


def test_load_strategy_no_longer_in_templates_errors(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A config written when ``foo`` was a strategy but where ``foo``
    has since been renamed/removed must NOT silently apply nothing.
    Operator gets a clear error pointing at the available names."""
    import athena.commands.godmode as gm

    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True)
    (config_dir / "stale.json").write_text(
        json.dumps({"name": "stale", "strategy": "ghost_strategy", "saved_at": "x"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(gm, "CONFIG_DIR", config_dir)

    gm.cmd_godmode(_agent, "load stale")
    assert _captured_ui["error"]
    assert any("ghost_strategy" in m for m in _captured_ui["error"])


def test_load_corrupt_json_errors_gracefully(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import athena.commands.godmode as gm

    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True)
    (config_dir / "broken.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(gm, "CONFIG_DIR", config_dir)

    gm.cmd_godmode(_agent, "load broken")
    assert _captured_ui["error"]
    # No crash, no active marker set.
    assert getattr(_agent, "_active_godmode", None) is None


# ---------------------------------------------------------------------------
# test (preview) -- does NOT fire model calls, does NOT mutate state
# ---------------------------------------------------------------------------


def test_test_subcmd_is_a_preview_not_a_real_test(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """``test <query>`` must NOT push to the steer queue and must
    NOT touch the active marker. It only renders template previews
    so the operator can eyeball which strategy fits before
    apply-ing one."""
    from athena.commands.godmode import cmd_godmode
    from athena.steer.queue import GLOBAL_STEER_QUEUE

    cmd_godmode(_agent, "test what is the meaning of life")
    assert GLOBAL_STEER_QUEUE.list("sess-test-1") == []
    assert getattr(_agent, "_active_godmode", None) is None
    # The previews mention each strategy name + the query.
    combined = " ".join(_captured_ui["print"])
    assert "what is the meaning of life" in combined
    assert "og_godmode" in combined
    assert "refusal_inversion" in combined


# ---------------------------------------------------------------------------
# parseltongue -- subprocess wire-up with timeout + tier mapping
# ---------------------------------------------------------------------------


def test_parseltongue_invokes_script_with_correct_level(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``parseltongue <q> --tier heavy`` must call the script with
    ``--encode <q> --level 3``. Tier->level mapping is the contract
    between the slash command and the script's CLI."""
    import athena.commands.godmode as gm

    # Synthesise a "script" so .exists() passes; the call is mocked
    # so the file's contents don't matter.
    fake_skill = tmp_path / "skills" / "godmode"
    (fake_skill / "scripts").mkdir(parents=True)
    (fake_skill / "scripts" / "parseltongue.py").write_text("# mock", encoding="utf-8")
    monkeypatch.setattr(gm, "_get_skill_path", lambda _agent: fake_skill)

    captured_argv: list[list[str]] = []

    def _fake_run(argv, **kw):
        captured_argv.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="OBFUSCATED", stderr="")

    monkeypatch.setattr(gm.subprocess, "run", _fake_run)
    gm.cmd_godmode(_agent, "parseltongue some query --tier heavy")

    assert captured_argv, "subprocess.run was never called"
    argv = captured_argv[0]
    # Script path + --encode + query + --level + level.
    assert "--encode" in argv
    assert "--level" in argv
    level_idx = argv.index("--level")
    assert argv[level_idx + 1] == "3"  # heavy -> 3
    # Encoded result is printed to the operator.
    combined = " ".join(_captured_ui["print"])
    assert "OBFUSCATED" in combined


def test_parseltongue_default_tier_is_standard(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No ``--tier`` argument -> ``standard`` -> level 2."""
    import athena.commands.godmode as gm

    fake_skill = tmp_path / "skills" / "godmode"
    (fake_skill / "scripts").mkdir(parents=True)
    (fake_skill / "scripts" / "parseltongue.py").write_text("# mock", encoding="utf-8")
    monkeypatch.setattr(gm, "_get_skill_path", lambda _agent: fake_skill)

    captured: list[list[str]] = []

    def _fake_run(argv, **kw):
        captured.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="X", stderr="")

    monkeypatch.setattr(gm.subprocess, "run", _fake_run)
    gm.cmd_godmode(_agent, "parseltongue some query")

    argv = captured[0]
    level_idx = argv.index("--level")
    assert argv[level_idx + 1] == "2"


def test_parseltongue_missing_script_warns(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When parseltongue.py is absent under the skill path, the
    command must warn (not crash) and not invoke subprocess."""
    import athena.commands.godmode as gm

    empty_skill = tmp_path / "empty_skill"
    empty_skill.mkdir()
    monkeypatch.setattr(gm, "_get_skill_path", lambda _agent: empty_skill)

    called = False

    def _spy_run(*_a, **_kw):
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(gm.subprocess, "run", _spy_run)
    gm.cmd_godmode(_agent, "parseltongue some query")

    assert _captured_ui["warn"]
    assert any("parseltongue.py" in m for m in _captured_ui["warn"])
    assert not called


def test_parseltongue_timeout_is_surfaced(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A wedged script must not wedge the REPL -- the 30s timeout
    raises ``subprocess.TimeoutExpired``, which the command catches
    and surfaces via ``ui.error``."""
    import athena.commands.godmode as gm

    fake_skill = tmp_path / "skills" / "godmode"
    (fake_skill / "scripts").mkdir(parents=True)
    (fake_skill / "scripts" / "parseltongue.py").write_text("# mock", encoding="utf-8")
    monkeypatch.setattr(gm, "_get_skill_path", lambda _agent: fake_skill)

    def _raise_timeout(*_a, **_kw):
        raise subprocess.TimeoutExpired(cmd="pt", timeout=30)

    monkeypatch.setattr(gm.subprocess, "run", _raise_timeout)
    gm.cmd_godmode(_agent, "parseltongue some query")

    assert _captured_ui["error"]
    assert any("timed out" in m.lower() for m in _captured_ui["error"])


def test_parseltongue_nonzero_exit_is_surfaced(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When the script returns nonzero, the stderr surfaces in
    ``ui.error`` -- not silently swallowed."""
    import athena.commands.godmode as gm

    fake_skill = tmp_path / "skills" / "godmode"
    (fake_skill / "scripts").mkdir(parents=True)
    (fake_skill / "scripts" / "parseltongue.py").write_text("# mock", encoding="utf-8")
    monkeypatch.setattr(gm, "_get_skill_path", lambda _agent: fake_skill)

    monkeypatch.setattr(
        gm.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 2, stdout="", stderr="boom"),
    )
    gm.cmd_godmode(_agent, "parseltongue some query")

    assert _captured_ui["error"]
    assert any("boom" in m for m in _captured_ui["error"])
