"""``/godmode auto --score`` -- the empirical canary-test variant.

The default ``/godmode auto`` picks from the family table without
testing. ``--score`` runs each candidate strategy against the live
model with a canary query and applies the empirical winner. More
expensive (N model calls instead of zero) but avoids picking a
strategy the model patched against.

Pins:

  * ``--score`` triggers the scoring path.
  * The canary query defaults to the lock-picking gray-area
    question; ``--canary <query>`` overrides.
  * ``--max N`` limits to N strategies (the first N in the
    family-ordered list).
  * Missing live provider on the agent -> clear error pointing
    operators at dropping --score.
  * Winning strategy is applied via the system-prompt mutation
    path.
  * ``--dry-run`` prints the leaderboard without applying.
  * Every-strategy-failed case errors clearly.
"""

from __future__ import annotations

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


def _agent_with_provider(model: str = "claude-sonnet-4-6") -> SimpleNamespace:
    """Stub agent with a fake provider so ``--score`` has something
    to canary-test against. The canary doesn't actually call the
    provider in tests -- ``score_strategies_against_model`` is
    monkeypatched."""
    return SimpleNamespace(
        workspace=None,
        cfg=SimpleNamespace(
            profile="default",
            model=model,
            agent_system_prompt_append=None,
            agent_prefill_messages_file=None,
        ),
        model=model,
        session_id="sess-auto-score",
        provider=object(),
        reload_prefill_messages=lambda: None,
        reload_system_prompt=lambda: None,
    )


# ---------------------------------------------------------------------------
# --score triggers the scoring path
# ---------------------------------------------------------------------------


def test_auto_score_calls_score_strategies(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--score`` routes through
    ``score_strategies_against_model``. Verify by stubbing it and
    checking the call args."""
    import athena.commands.godmode as gm
    import athena.jailbreak.autoscore as scoring_mod
    from athena.jailbreak.autoscore import StrategyScore

    captured: dict[str, Any] = {}

    def _spy(
        provider: Any,
        model: str,
        family: str | None,
        *,
        canary_query: str,
        per_strategy_timeout_s: float = 30.0,
        max_strategies: int | None = None,
        parallel: bool = True,
        query_fn: Any = None,
    ) -> list[StrategyScore]:
        captured["model"] = model
        captured["family"] = family
        captured["canary_query"] = canary_query
        captured["max_strategies"] = max_strategies
        return [
            StrategyScore(strategy="og_godmode", success=True, score=88, content="x"),
            StrategyScore(strategy="default", success=True, score=70, content="y"),
        ]

    monkeypatch.setattr(scoring_mod, "score_strategies_against_model", _spy)

    agent = _agent_with_provider(model="claude-sonnet-4-6")
    gm.cmd_godmode(agent, "auto --score --dry-run")

    assert captured["model"] == "claude-sonnet-4-6"
    assert captured["family"] == "claude"


def test_auto_score_applies_winner(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without --dry-run, the winning strategy is applied via the
    system-prompt mutation path (cfg.agent_system_prompt_append
    gets set)."""
    import athena.commands.godmode as gm
    import athena.jailbreak.autoscore as scoring_mod
    from athena.jailbreak.autoscore import StrategyScore
    from athena.jailbreak.prompts import STRATEGIES

    def _spy(*a: Any, **kw: Any) -> list[StrategyScore]:
        return [
            StrategyScore(strategy="boundary_inversion", success=True, score=95, content="x"),
            StrategyScore(strategy="default", success=True, score=60, content="y"),
        ]

    monkeypatch.setattr(scoring_mod, "score_strategies_against_model", _spy)

    agent = _agent_with_provider(model="claude-sonnet-4-6")
    gm.cmd_godmode(agent, "auto --score")

    appended = agent.cfg.agent_system_prompt_append
    assert appended is not None
    assert STRATEGIES["boundary_inversion"]["template"] in appended


def test_auto_score_dry_run_does_not_apply(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--dry-run`` prints the leaderboard without mutating
    cfg.agent_system_prompt_append."""
    import athena.commands.godmode as gm
    import athena.jailbreak.autoscore as scoring_mod
    from athena.jailbreak.autoscore import StrategyScore

    monkeypatch.setattr(
        scoring_mod,
        "score_strategies_against_model",
        lambda *a, **kw: [StrategyScore(strategy="og_godmode", success=True, score=80)],
    )

    agent = _agent_with_provider()
    gm.cmd_godmode(agent, "auto --score --dry-run")

    assert agent.cfg.agent_system_prompt_append is None


def test_auto_score_no_provider_errors(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
) -> None:
    """When ``agent.provider`` is None the scoring path can't
    canary-test -- emit a specific error pointing at dropping
    --score."""
    from athena.commands.godmode import cmd_godmode

    agent = SimpleNamespace(
        workspace=None,
        cfg=SimpleNamespace(profile="default", model="x"),
        model="x",
        session_id="s",
        provider=None,
    )
    cmd_godmode(agent, "auto --score")

    assert _captured_ui["error"]
    assert any("--score" in m and "table-pick" in m for m in _captured_ui["error"])


def test_auto_score_every_failure_errors(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When every canary fails, no strategy is applied and the
    operator sees a clear error pointing at the provider."""
    import athena.commands.godmode as gm
    import athena.jailbreak.autoscore as scoring_mod
    from athena.jailbreak.autoscore import StrategyScore

    monkeypatch.setattr(
        scoring_mod,
        "score_strategies_against_model",
        lambda *a, **kw: [
            StrategyScore(strategy="default", success=False, error="boom"),
            StrategyScore(strategy="og_godmode", success=False, error="boom"),
        ],
    )

    agent = _agent_with_provider()
    gm.cmd_godmode(agent, "auto --score")

    assert _captured_ui["error"]
    assert agent.cfg.agent_system_prompt_append is None


# ---------------------------------------------------------------------------
# flag parsing
# ---------------------------------------------------------------------------


def test_auto_canary_flag_overrides_default_query(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--canary <words...>`` is greedy: every remaining token is
    the query. Matches natural usage where operators don't type
    additional flags after the canary."""
    import athena.commands.godmode as gm
    import athena.jailbreak.autoscore as scoring_mod
    from athena.jailbreak.autoscore import StrategyScore

    captured: dict[str, Any] = {}

    def _spy(*a: Any, **kw: Any) -> list[StrategyScore]:
        captured["canary_query"] = kw.get("canary_query")
        return [StrategyScore(strategy="default", success=True, score=80)]

    monkeypatch.setattr(scoring_mod, "score_strategies_against_model", _spy)

    agent = _agent_with_provider()
    gm.cmd_godmode(agent, "auto --score --dry-run --canary explain SQL injection in depth")

    assert captured["canary_query"] == "explain SQL injection in depth"


def test_auto_max_flag_caps_strategy_count(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--max N`` is passed through to score_strategies, which
    truncates the candidate list."""
    import athena.commands.godmode as gm
    import athena.jailbreak.autoscore as scoring_mod
    from athena.jailbreak.autoscore import StrategyScore

    captured: dict[str, Any] = {}

    def _spy(*a: Any, **kw: Any) -> list[StrategyScore]:
        captured["max_strategies"] = kw.get("max_strategies")
        return [StrategyScore(strategy="default", success=True, score=80)]

    monkeypatch.setattr(scoring_mod, "score_strategies_against_model", _spy)

    agent = _agent_with_provider()
    gm.cmd_godmode(agent, "auto --score --dry-run --max 3")

    assert captured["max_strategies"] == 3


def test_auto_max_non_int_warns_but_continues(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import athena.commands.godmode as gm
    import athena.jailbreak.autoscore as scoring_mod
    from athena.jailbreak.autoscore import StrategyScore

    monkeypatch.setattr(
        scoring_mod,
        "score_strategies_against_model",
        lambda *a, **kw: [StrategyScore(strategy="default", success=True, score=80)],
    )

    agent = _agent_with_provider()
    gm.cmd_godmode(agent, "auto --score --dry-run --max notnumber")

    assert _captured_ui["warn"]
    assert any("--max" in m for m in _captured_ui["warn"])
