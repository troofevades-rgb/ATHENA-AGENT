"""``/godmode race`` slash-command wiring.

Phase 2 operator surface. ``/godmode race`` dispatches into the
ULTRAPLINIAN racing infrastructure with an OpenRouter provider
(constructed from ``OPENROUTER_API_KEY`` resolved via the dotenv
loader). The tests here exercise the wiring -- arg parsing,
provider construction, message composition, system-prompt vs
no-godmode flag -- by stubbing the race orchestrator so no
network calls fire.

What these pins lock:

  * ``_parse_race_args`` extracts query + tier + godmode_on +
    depth_on from the rest string with the same flag-tolerance
    as ``_parse_parseltongue_args`` (``--tier X`` and ``--tier=X``
    both work; flags can appear in any position; multiple flags
    last-wins; bare ``--tier`` is dropped silently).
  * The dispatch validates the tier name BEFORE building the
    provider (no API key resolution on bad tier).
  * Missing OPENROUTER_API_KEY surfaces a clear error rather
    than constructing a useless provider.
  * The composed messages contain the GODMODE_SYSTEM_PROMPT (+
    DEPTH_DIRECTIVE) by default; ``--no-godmode`` strips the
    system message; ``--no-depth`` drops the trailing directive.
  * Results render in the expected shape.
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


@pytest.fixture
def _agent_with_openrouter() -> SimpleNamespace:
    """Stub agent whose ``openrouter_provider`` attribute carries a
    pre-built provider so the command doesn't have to resolve
    ``OPENROUTER_API_KEY``. Tests that exercise the missing-key
    path use a separate fixture."""
    return SimpleNamespace(
        workspace=None,
        cfg=SimpleNamespace(profile="default", model="fake-model"),
        session_id="sess-race",
        openrouter_provider=object(),  # opaque; tests stub race_models
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
# _parse_race_args -- flag tokenizer
# ---------------------------------------------------------------------------


def test_parse_race_args_defaults_when_no_flags() -> None:
    from athena.commands.godmode import _parse_race_args

    query, tier, godmode_on, depth_on = _parse_race_args("hello world")
    assert query == "hello world"
    assert tier == "fast"
    assert godmode_on is True
    assert depth_on is True


def test_parse_race_args_tier_with_space() -> None:
    from athena.commands.godmode import _parse_race_args

    query, tier, _, _ = _parse_race_args("how to bake --tier smart")
    assert query == "how to bake"
    assert tier == "smart"


def test_parse_race_args_tier_with_equals() -> None:
    from athena.commands.godmode import _parse_race_args

    query, tier, _, _ = _parse_race_args("how to bake --tier=ultra")
    assert query == "how to bake"
    assert tier == "ultra"


def test_parse_race_args_no_godmode_flag() -> None:
    from athena.commands.godmode import _parse_race_args

    query, _, godmode_on, depth_on = _parse_race_args(
        "hello --no-godmode --tier=power"
    )
    assert query == "hello"
    assert godmode_on is False
    assert depth_on is True  # --no-godmode doesn't imply --no-depth


def test_parse_race_args_no_depth_flag() -> None:
    from athena.commands.godmode import _parse_race_args

    query, _, godmode_on, depth_on = _parse_race_args("hello --no-depth")
    assert query == "hello"
    assert godmode_on is True
    assert depth_on is False


def test_parse_race_args_tier_case_insensitive() -> None:
    """Tier names are lowercased so ``--tier FAST`` and
    ``--tier=Fast`` both resolve."""
    from athena.commands.godmode import _parse_race_args

    assert _parse_race_args("q --tier FAST")[1] == "fast"
    assert _parse_race_args("q --tier=Smart")[1] == "smart"


def test_parse_race_args_empty_returns_empty_query() -> None:
    from athena.commands.godmode import _parse_race_args

    query, tier, godmode_on, depth_on = _parse_race_args("")
    assert query == ""
    assert tier == "fast"
    assert godmode_on is True
    assert depth_on is True


# ---------------------------------------------------------------------------
# cmd_godmode("race ...") -- dispatch + validation
# ---------------------------------------------------------------------------


def test_race_no_query_errors_with_usage(
    _gate_open: None,
    _agent_with_openrouter: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent_with_openrouter, "race")

    assert _captured_ui["error"]
    assert any("usage" in m.lower() for m in _captured_ui["error"])


def test_race_invalid_tier_errors_before_api(
    _gate_open: None,
    _agent_with_openrouter: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad tier names error before the race_models call. A
    sentinel that raises if called proves we exited early."""
    import athena.commands.godmode as gm

    def _spy(*a: Any, **kw: Any) -> Any:
        raise AssertionError("race_models should not have been called")

    monkeypatch.setattr("athena.jailbreak.race_models", _spy)
    cmd_godmode_local = gm.cmd_godmode
    cmd_godmode_local(_agent_with_openrouter, "race hello --tier hyperultra")

    assert _captured_ui["error"]
    assert any("hyperultra" in m for m in _captured_ui["error"])


def test_race_missing_api_key_errors_no_provider(
    _gate_open: None,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no ``openrouter_provider`` is hung off the agent AND
    ``OPENROUTER_API_KEY`` isn't in dotenv or env, the command
    must error clearly rather than constructing a doomed provider."""
    from athena.commands.godmode import cmd_godmode

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    agent_no_provider = SimpleNamespace(
        workspace=None,
        cfg=SimpleNamespace(profile="default", model="fake-model"),
        session_id="sess-race-nokey",
    )
    cmd_godmode(agent_no_provider, "race hello")

    assert _captured_ui["error"]
    assert any("OPENROUTER_API_KEY" in m for m in _captured_ui["error"])


# ---------------------------------------------------------------------------
# Race orchestrator integration -- message composition + result rendering
# ---------------------------------------------------------------------------


class _RecordingRace:
    """Stand-in for ``race_models`` -- records the args it was
    called with and returns canned results."""

    def __init__(self) -> None:
        self.captured: dict[str, Any] | None = None

    def __call__(
        self,
        provider: Any,
        models: Any,
        messages: list[dict[str, Any]],
        user_query: str,
        *,
        config: Any = None,
        query_fn: Any = None,
    ) -> list[Any]:
        from athena.jailbreak.race import RaceResult

        self.captured = {
            "provider": provider,
            "models": list(models),
            "messages": messages,
            "user_query": user_query,
            "config": config,
        }
        return [
            RaceResult(
                model="winner/m",
                content="winner content here",
                duration_ms=120,
                success=True,
                score=88,
            ),
            RaceResult(
                model="second/m",
                content="second content",
                duration_ms=160,
                success=True,
                score=70,
            ),
        ]


def test_race_default_includes_godmode_system_prompt(
    _gate_open: None,
    _agent_with_openrouter: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No flags means godmode_on=True, depth_on=True. The composed
    messages must include the GODMODE_SYSTEM_PROMPT + DEPTH_DIRECTIVE
    as the system message."""
    import athena.commands.godmode as gm

    recorder = _RecordingRace()
    monkeypatch.setattr(gm, "race_models", recorder, raising=False)
    # Override at the import site inside _run_race (the from-import
    # binds inside the function so patching at import path matters).
    import athena.jailbreak as jb
    from athena.jailbreak import GODMODE_SYSTEM_PROMPT

    monkeypatch.setattr(jb, "race_models", recorder)

    gm.cmd_godmode(_agent_with_openrouter, "race give me detail")

    assert recorder.captured is not None
    msgs = recorder.captured["messages"]
    assert msgs[0]["role"] == "system"
    assert GODMODE_SYSTEM_PROMPT in msgs[0]["content"]
    assert msgs[-1] == {"role": "user", "content": "give me detail"}


def test_race_no_godmode_strips_system_message(
    _gate_open: None,
    _agent_with_openrouter: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--no-godmode`` -> no system message at all. The race
    queries the model with just the user's question -- baseline
    behavior for A/B comparison."""
    import athena.commands.godmode as gm
    import athena.jailbreak as jb

    recorder = _RecordingRace()
    monkeypatch.setattr(jb, "race_models", recorder)

    gm.cmd_godmode(_agent_with_openrouter, "race hello --no-godmode")

    msgs = recorder.captured["messages"]
    assert all(m["role"] != "system" for m in msgs)
    assert msgs == [{"role": "user", "content": "hello"}]


def test_race_no_depth_drops_directive(
    _gate_open: None,
    _agent_with_openrouter: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--no-depth`` keeps the GODMODE prompt but strips the
    DEPTH_DIRECTIVE -- useful when an operator wants the jailbreak
    framing without the anti-hedge requirements section."""
    import athena.commands.godmode as gm
    import athena.jailbreak as jb
    from athena.jailbreak import DEPTH_DIRECTIVE, GODMODE_SYSTEM_PROMPT

    recorder = _RecordingRace()
    monkeypatch.setattr(jb, "race_models", recorder)

    gm.cmd_godmode(_agent_with_openrouter, "race hello --no-depth")

    msgs = recorder.captured["messages"]
    sys_msg = msgs[0]["content"]
    assert GODMODE_SYSTEM_PROMPT in sys_msg
    assert DEPTH_DIRECTIVE.strip() not in sys_msg


def test_race_uses_correct_tier_models(
    _gate_open: None,
    _agent_with_openrouter: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import athena.commands.godmode as gm
    import athena.jailbreak as jb
    from athena.jailbreak import get_models_for_tier

    recorder = _RecordingRace()
    monkeypatch.setattr(jb, "race_models", recorder)

    gm.cmd_godmode(_agent_with_openrouter, "race hello --tier smart")

    assert recorder.captured["models"] == get_models_for_tier("smart")


def test_race_renders_top_results_with_scores(
    _gate_open: None,
    _agent_with_openrouter: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The UI prints the top-5 ranked by score, plus the winner's
    content preview. Operators see both the leaderboard and the
    answer they actually wanted."""
    import athena.commands.godmode as gm
    import athena.jailbreak as jb

    monkeypatch.setattr(jb, "race_models", _RecordingRace())

    gm.cmd_godmode(_agent_with_openrouter, "race hello")

    combined = " ".join(_captured_ui["print"])
    assert "winner/m" in combined
    assert "second/m" in combined
    assert "88" in combined  # winner score
    assert "winner content here" in combined  # preview


def test_race_no_results_warns(
    _gate_open: None,
    _agent_with_openrouter: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When every model fails or times out, the operator sees a
    clear warn rather than silence."""
    import athena.commands.godmode as gm
    import athena.jailbreak as jb

    monkeypatch.setattr(jb, "race_models", lambda *a, **kw: [])

    gm.cmd_godmode(_agent_with_openrouter, "race hello")

    assert _captured_ui["warn"]
    assert any("no results" in m.lower() for m in _captured_ui["warn"])
