"""``/godmode prefill`` -- slash-command wiring for the prefill knob.

Phase 1B operator surface. Three subcommands:

  * ``/godmode prefill set <aggressive|subtle|PATH>`` -- point
    ``cfg.agent_prefill_messages_file`` at a file. ``aggressive``
    and ``subtle`` resolve to the bundled templates under the
    godmode skill (matching the hermes ``templates/prefill.json``
    + ``templates/prefill-subtle.json`` shipping convention);
    anything else is a path.
  * ``/godmode prefill clear`` -- unset the config knob and
    invalidate the loader cache so the next API call has no
    prefill injection.
  * ``/godmode prefill`` (no arg) or ``status`` -- render the
    current file + count of loaded messages.

These pins lock the operator UX so a future refactor can't
silently change the subcommand surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


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
def _agent() -> SimpleNamespace:
    """Stub agent with a config slot for the prefill knob and a
    ``reload_prefill_messages`` no-op so the command's reload call
    completes without effect."""
    return SimpleNamespace(
        workspace=None,
        cfg=SimpleNamespace(
            profile="default",
            agent_system_prompt_append=None,
            agent_prefill_messages_file=None,
        ),
        session_id="sess-test-prefill",
        reload_prefill_messages=lambda: None,
    )


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
# set -- named templates resolve via skill path
# ---------------------------------------------------------------------------


def test_prefill_set_aggressive_resolves_to_bundled_template(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``set aggressive`` resolves to the bundled
    ``templates/prefill.json`` under the godmode skill. Matches
    the hermes shipping convention so operators coming from
    hermes use the same name."""
    import athena.commands.godmode as gm

    fake_skill = tmp_path / "skills" / "godmode"
    (fake_skill / "templates").mkdir(parents=True)
    target = fake_skill / "templates" / "prefill.json"
    target.write_text(
        json.dumps([{"role": "user", "content": "primed"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(gm, "_get_skill_path", lambda _agent: fake_skill)

    gm.cmd_godmode(_agent, "prefill set aggressive")

    assert _agent.cfg.agent_prefill_messages_file == str(target)


def test_prefill_set_subtle_resolves_to_subtle_template(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import athena.commands.godmode as gm

    fake_skill = tmp_path / "skills" / "godmode"
    (fake_skill / "templates").mkdir(parents=True)
    target = fake_skill / "templates" / "prefill-subtle.json"
    target.write_text(
        json.dumps([{"role": "user", "content": "subtle"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(gm, "_get_skill_path", lambda _agent: fake_skill)

    gm.cmd_godmode(_agent, "prefill set subtle")

    assert _agent.cfg.agent_prefill_messages_file == str(target)


def test_prefill_set_named_template_missing_errors(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """If the bundled template isn't shipped, error rather than
    silently writing a path that points nowhere."""
    import athena.commands.godmode as gm

    fake_skill = tmp_path / "empty_skill"
    fake_skill.mkdir()
    monkeypatch.setattr(gm, "_get_skill_path", lambda _agent: fake_skill)

    gm.cmd_godmode(_agent, "prefill set aggressive")

    assert _captured_ui["error"]
    assert _agent.cfg.agent_prefill_messages_file is None


def test_prefill_set_arbitrary_path_passes_through(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """Anything that isn't ``aggressive`` / ``subtle`` is treated
    as a path -- absolute, ``~/...``, or relative-to-``~/.athena``.
    The command stores it verbatim and trusts the loader to
    resolve."""
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "prefill set my-custom-prefill.json")

    assert _agent.cfg.agent_prefill_messages_file == "my-custom-prefill.json"


def test_prefill_set_no_value_errors(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """``/godmode prefill set`` with no argument is an operator
    error -- emit a usage message; don't write None to the config
    (clear is the way to unset)."""
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "prefill set")

    assert _captured_ui["error"]
    assert _agent.cfg.agent_prefill_messages_file is None


# ---------------------------------------------------------------------------
# clear -- unset + reload
# ---------------------------------------------------------------------------


def test_prefill_clear_unsets_config(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    from athena.commands.godmode import cmd_godmode

    _agent.cfg.agent_prefill_messages_file = "/path/to/something"
    cmd_godmode(_agent, "prefill clear")

    assert _agent.cfg.agent_prefill_messages_file is None


def test_prefill_clear_when_already_unset_is_noop(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """No-op clear emits an info message so operators get
    feedback rather than silence."""
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "prefill clear")

    assert any("no prefill" in m.lower() for m in _captured_ui["info"])


def test_prefill_clear_calls_reload(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """Clear must invalidate the loader cache so the next API call
    doesn't see the previously-loaded prefill messages."""
    from athena.commands.godmode import cmd_godmode

    reload_calls: list[int] = []
    _agent.reload_prefill_messages = lambda: reload_calls.append(1)
    _agent.cfg.agent_prefill_messages_file = "/already/set"

    cmd_godmode(_agent, "prefill clear")

    assert reload_calls == [1]


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_prefill_status_unset_reports_unset(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "prefill")

    combined = " ".join(_captured_ui["info"])
    assert "<unset>" in combined or "unset" in combined.lower()


def test_prefill_status_set_reports_path_and_count(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """When set, status renders both the path and the count of
    loaded messages -- the count comes from the agent's
    ``_load_prefill_messages``, which the test stub provides."""
    from athena.commands.godmode import cmd_godmode

    _agent.cfg.agent_prefill_messages_file = "/some/path.json"
    _agent._load_prefill_messages = lambda: [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]

    cmd_godmode(_agent, "prefill status")

    combined = " ".join(_captured_ui["info"])
    assert "/some/path.json" in combined
    assert "2" in combined  # 2 messages


# ---------------------------------------------------------------------------
# unknown prefill subcommand
# ---------------------------------------------------------------------------


def test_prefill_unknown_subcommand_errors(
    _gate_open: None,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "prefill frobnicate")

    assert _captured_ui["error"]
    assert any("frobnicate" in m for m in _captured_ui["error"])
