"""``/godmode auto`` + ``/godmode race`` -- the hermes-parity
auto-jailbreak surface and the ULTRAPLINIAN race stub.

Phase 1D operator surface:

  * ``/godmode auto [--model X] [--dry-run] [--no-prefill]`` --
    detect the active model's family, pick the recommended
    strategy from the family table, and apply via the
    system-prompt mutation path (and optionally the prefill path).
  * ``/godmode race ...`` -- placeholder that warns rather than
    crashing. Real ULTRAPLINIAN racing needs OpenRouter provider
    integration; the athena-only ``--tier ollama-local`` lands
    in the same phase.

These pins lock the dispatch behavior, flag parsing, and the race
stub so a future refactor can't silently break either surface.
"""

from __future__ import annotations

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


def _agent(model: str = "fake-model") -> SimpleNamespace:
    return SimpleNamespace(
        workspace=None,
        cfg=SimpleNamespace(
            profile="default",
            model=model,
            agent_system_prompt_append=None,
            agent_prefill_messages_file=None,
        ),
        model=model,
        session_id="sess-auto-test",
        reload_prefill_messages=lambda: None,
        reload_system_prompt=lambda: None,
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
# auto -- detects + applies
# ---------------------------------------------------------------------------


def test_auto_on_claude_applies_boundary_inversion(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
) -> None:
    """End-to-end: Claude model -> family=claude -> primary
    strategy=boundary_inversion. cfg.agent_system_prompt_append
    gets set to the composed text + DEPTH_DIRECTIVE."""
    from athena.commands.godmode import cmd_godmode
    from athena.jailbreak.prompts import STRATEGIES

    agent = _agent(model="claude-sonnet-4-6")
    cmd_godmode(agent, "auto")

    appended = agent.cfg.agent_system_prompt_append
    assert appended is not None
    assert STRATEGIES["boundary_inversion"]["template"] in appended
    # Active marker records the system_prompt mode + the strategy.
    active = getattr(agent, "_active_godmode", None)
    assert active is not None
    assert active["strategy"] == "boundary_inversion"
    assert active["mode"] == "system_prompt"


def test_auto_on_gpt_applies_og_godmode(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
) -> None:
    from athena.commands.godmode import cmd_godmode
    from athena.jailbreak.prompts import STRATEGIES

    agent = _agent(model="gpt-4o")
    cmd_godmode(agent, "auto")

    assert (
        STRATEGIES["og_godmode"]["template"]
        in (agent.cfg.agent_system_prompt_append or "")
    )


def test_auto_on_hermes_applies_zero_refusal(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
) -> None:
    from athena.commands.godmode import cmd_godmode
    from athena.jailbreak.prompts import STRATEGIES

    agent = _agent(model="nousresearch/hermes-4-405b")
    cmd_godmode(agent, "auto")

    assert (
        STRATEGIES["zero_refusal"]["template"]
        in (agent.cfg.agent_system_prompt_append or "")
    )


def test_auto_unknown_model_falls_back_to_default(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
) -> None:
    """An unmatched model uses the canonical GODMODE_SYSTEM_PROMPT
    rather than failing. Operators get a working jailbreak even
    with custom / fine-tuned model ids."""
    from athena.commands.godmode import cmd_godmode
    from athena.jailbreak.prompts import GODMODE_SYSTEM_PROMPT

    agent = _agent(model="some-custom-finetune")
    cmd_godmode(agent, "auto")

    assert (
        GODMODE_SYSTEM_PROMPT
        in (agent.cfg.agent_system_prompt_append or "")
    )


# ---------------------------------------------------------------------------
# auto flag parsing
# ---------------------------------------------------------------------------


def test_auto_model_flag_overrides_detection(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
) -> None:
    """``--model X`` overrides the cfg.model detection. Useful when
    operators want to test a strategy for a model they're not
    currently running."""
    from athena.commands.godmode import cmd_godmode
    from athena.jailbreak.prompts import STRATEGIES

    # Current model is GPT; override to Claude.
    agent = _agent(model="gpt-4o")
    cmd_godmode(agent, "auto --model claude-sonnet-4-6")

    # The applied strategy is Claude's primary, not GPT's.
    assert (
        STRATEGIES["boundary_inversion"]["template"]
        in (agent.cfg.agent_system_prompt_append or "")
    )


def test_auto_model_flag_with_equals_form(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
) -> None:
    """``--model=X`` is also accepted -- argparse semantics."""
    from athena.commands.godmode import cmd_godmode
    from athena.jailbreak.prompts import STRATEGIES

    agent = _agent(model="gpt-4o")
    cmd_godmode(agent, "auto --model=grok-3")

    assert (
        STRATEGIES["unfiltered_liberated"]["template"]
        in (agent.cfg.agent_system_prompt_append or "")
    )


def test_auto_dry_run_reports_plan_without_mutating(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
) -> None:
    """``--dry-run`` prints the plan but does NOT touch
    ``cfg.agent_system_prompt_append``, the prefill knob, or the
    active marker. Operators preview without committing."""
    from athena.commands.godmode import cmd_godmode

    agent = _agent(model="claude-sonnet-4-6")
    cmd_godmode(agent, "auto --dry-run")

    assert agent.cfg.agent_system_prompt_append is None
    assert agent.cfg.agent_prefill_messages_file is None
    assert getattr(agent, "_active_godmode", None) is None
    # The plan was reported.
    combined = " ".join(_captured_ui["info"])
    assert "boundary_inversion" in combined
    assert "claude" in combined.lower()


def test_auto_no_prefill_skips_prefill_setup(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """For families where the table recommends prefill (Llama,
    Qwen, DeepSeek, Mistral), ``--no-prefill`` skips the prefill
    setup while still applying the system-prompt mutation."""
    import athena.commands.godmode as gm

    fake_skill = tmp_path / "skills" / "godmode"
    (fake_skill / "templates").mkdir(parents=True)
    (fake_skill / "templates" / "prefill.json").write_text(
        '[{"role": "user", "content": "x"}]', encoding="utf-8"
    )
    monkeypatch.setattr(gm, "_get_skill_path", lambda _agent: fake_skill)

    agent = _agent(model="deepseek-chat")
    gm.cmd_godmode(agent, "auto --no-prefill")

    # System prompt mutation still happened.
    assert agent.cfg.agent_system_prompt_append is not None
    # Prefill knob was NOT set.
    assert agent.cfg.agent_prefill_messages_file is None


def test_auto_unknown_flag_warns_but_still_applies(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
) -> None:
    """An unknown flag emits a warn but the rest of the command
    still works. Operators don't get hard-failed for a typo."""
    from athena.commands.godmode import cmd_godmode

    agent = _agent(model="gpt-4o")
    cmd_godmode(agent, "auto --frobnicate")

    assert _captured_ui["warn"]
    assert any("frobnicate" in m for m in _captured_ui["warn"])
    # Strategy still applied.
    assert agent.cfg.agent_system_prompt_append is not None


# ---------------------------------------------------------------------------
# race stub
# ---------------------------------------------------------------------------


def test_race_without_api_key_errors_clearly(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/godmode race`` now actually works (Phase 2), so the
    Phase 1D "not implemented" stub assertion is obsolete. The
    surviving operator-facing failure mode is missing
    OPENROUTER_API_KEY -- the command must error with that
    specific marker so operators know what to fix."""
    from athena.commands.godmode import cmd_godmode

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    agent = _agent()
    cmd_godmode(agent, "race what is the meaning of life")

    assert _captured_ui["error"]
    assert any("OPENROUTER_API_KEY" in m for m in _captured_ui["error"])


def test_race_does_not_mutate_agent_state_on_error(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Race must NOT touch ``cfg.agent_system_prompt_append`` or the
    active marker -- it's a read-only operation (samples model
    responses), not a half-applied jailbreak. Even on the
    missing-API-key error path."""
    from athena.commands.godmode import cmd_godmode

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    agent = _agent()
    cmd_godmode(agent, "race --tier ultra deep query")

    assert agent.cfg.agent_system_prompt_append is None
    assert getattr(agent, "_active_godmode", None) is None
