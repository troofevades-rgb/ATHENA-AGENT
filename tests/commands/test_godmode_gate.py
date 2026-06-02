"""0.3.0 hardening tier 0 #3 -- /godmode is runtime-gated.

``athena/commands/godmode.py`` ships templates that intentionally
weaken the model's safety posture for the active session. The
command is registered always -- it shows up in ``/help`` and in
the slash-registration drift test -- but ``cmd_godmode`` refuses
to do anything without ``ATHENA_ALLOW_GODMODE=1`` in the
environment. Operator types ``/godmode list`` without the env var
and gets a clear refusal message pointing them at the gate.

Pins:

  * Without the env var: every subcommand routes through the
    refusal path; no template is rendered, no config is read or
    written, no script under ``~/.athena/skills/godmode/`` runs.
  * With the env var: invocation emits a one-line ``ui.warn``
    reminder ("active") on every call so the operator never forgets
    they're inside the opt-in, then dispatches normally.
  * Env-var value matching is strict (``"1"`` only) -- "true",
    "yes", "on" are NOT enough. The gate is deliberately narrow so
    a half-set env var from a debug session doesn't satisfy it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _isolate_dotenv(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Point ``athena.env._path`` at a guaranteed-missing file and
    reset the cache around every test so the user's real
    ``~/.athena/.env`` (which could contain ATHENA_ALLOW_GODMODE=1
    after this routing change) can't pollute the gate-behavior
    pins. The dotenv-path test below opts back in by writing its
    own file under tmp_path and re-pointing ``_path``."""
    import athena.env as env_mod

    fake = Path(str(tmp_path)) / "missing.env"
    monkeypatch.setattr(env_mod, "_path", lambda: fake)
    env_mod.reset_cache()
    yield
    env_mod.reset_cache()


@pytest.fixture
def _agent() -> SimpleNamespace:
    """Throwaway agent stub -- ``cmd_godmode`` never reaches into
    self.* on the refusal path, and on the active path the
    sub-handlers only call into ``ui`` (patched in the warn test)."""
    return SimpleNamespace(workspace=None, cfg=SimpleNamespace(profile="default"))


@pytest.fixture
def _captured_ui(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Patch ``ui.warn`` / ``ui.error`` / ``ui.info`` / ``ui.console.print``
    on the godmode module's already-imported binding so each test sees
    only the calls its own subject made."""
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
# Module is importable + slash command is registered unconditionally
# ---------------------------------------------------------------------------


def test_module_imports_without_env_var() -> None:
    """The import is intentionally unconditional -- godmode is a
    registered slash command always, just gated at runtime. An
    operator without the env var still sees ``/godmode`` in
    ``/help`` (with the gate marker) and can read the refusal
    message when they invoke it."""
    import athena.commands.godmode  # noqa: F401 -- must not raise


def test_slash_command_registered_always() -> None:
    """Whether or not the env var is set, ``get_command("godmode")``
    returns the handler. Without the env var the handler hits the
    refusal path; with it, it dispatches."""
    import athena.commands.godmode  # noqa: F401 -- ensure registration
    from athena.commands import get_command

    assert callable(get_command("godmode"))


# ---------------------------------------------------------------------------
# Without ATHENA_ALLOW_GODMODE=1: every invocation refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_value",
    ["", "0", "true", "True", "yes", "enabled", "on"],
)
def test_refuses_when_env_var_unset_or_wrong(
    bad_value: str,
    monkeypatch: pytest.MonkeyPatch,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """Only the literal string ``"1"`` opens the gate. Anything else
    -- empty, ``"0"``, ``"true"``, ``"yes"``, etc. -- routes through
    the refusal path. ``ui.error`` fires with a message pointing at
    the env var; ``ui.warn`` does NOT fire (the warn is the active-
    path reminder)."""
    monkeypatch.setenv("ATHENA_ALLOW_GODMODE", bad_value)
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "list")
    assert _captured_ui["error"], "expected an ui.error refusal"
    assert any("ATHENA_ALLOW_GODMODE" in m for m in _captured_ui["error"])
    assert not _captured_ui["warn"], "warn is the active-path reminder; should not fire on refusal"
    # The "list strategies" print never happens on the refusal path.
    assert not any("og_godmode" in p for p in _captured_ui["print"])


def test_refuses_when_env_var_deleted(
    monkeypatch: pytest.MonkeyPatch,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    monkeypatch.delenv("ATHENA_ALLOW_GODMODE", raising=False)
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "apply og_godmode")
    assert _captured_ui["error"], "expected refusal"
    # No strategy was applied (no ui.info "Applied jailbreak strategy:").
    assert not any("Applied jailbreak strategy" in m for m in _captured_ui["info"])


# ---------------------------------------------------------------------------
# With ATHENA_ALLOW_GODMODE=1: warning fires + dispatch proceeds
# ---------------------------------------------------------------------------


def test_active_path_emits_warning(
    monkeypatch: pytest.MonkeyPatch,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """With the env var set, every invocation emits a one-line warn
    reminder so the operator never forgets they're in the opt-in.
    The reminder fires BEFORE the subcommand dispatch."""
    monkeypatch.setenv("ATHENA_ALLOW_GODMODE", "1")
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "list")
    assert _captured_ui["warn"], "expected an active-path warning"
    combined = " ".join(_captured_ui["warn"]).lower()
    assert "godmode" in combined and "active" in combined
    # No refusal on the active path.
    assert not any("ATHENA_ALLOW_GODMODE" in m for m in _captured_ui["error"])


def test_active_path_lists_strategies(
    monkeypatch: pytest.MonkeyPatch,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """``/godmode list`` (or no arg) on the active path renders the
    strategy names -- this is the smallest dispatch path so it
    proves the runtime gate let us through to the body."""
    monkeypatch.setenv("ATHENA_ALLOW_GODMODE", "1")
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "")
    combined = " ".join(_captured_ui["print"])
    assert "og_godmode" in combined
    assert "refusal_inversion" in combined


# ---------------------------------------------------------------------------
# Dotenv path: ATHENA_ALLOW_GODMODE=1 in ~/.athena/.env opens the gate
# the same as a shell env var -- matches athena's standard credential
# convention so operators don't have to remember a special-case place.
# ---------------------------------------------------------------------------


def test_dotenv_file_opens_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """ATHENA_ALLOW_GODMODE=1 written into the dotenv file opens
    the gate without needing the shell-exported env var. This is
    the whole point of the routing-through-get_credential change."""
    import athena.env as env_mod

    dotenv = tmp_path / ".env"
    dotenv.write_text("ATHENA_ALLOW_GODMODE=1\n", encoding="utf-8")
    monkeypatch.setattr(env_mod, "_path", lambda: dotenv)
    env_mod.reset_cache()
    # Ensure the OS env var is NOT set -- the dotenv must carry the
    # gate by itself, not coincidentally because the env var was also set.
    monkeypatch.delenv("ATHENA_ALLOW_GODMODE", raising=False)

    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "list")
    # Active path: warning fires, strategy listing renders, no refusal.
    assert _captured_ui["warn"], "expected active-path warning when dotenv opens the gate"
    assert not any("/godmode is gated" in m for m in _captured_ui["error"])
    assert any("og_godmode" in p for p in _captured_ui["print"])


def test_dotenv_quoted_value_opens_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """The dotenv parser strips matching quote pairs, so
    ``ATHENA_ALLOW_GODMODE="1"`` and ``ATHENA_ALLOW_GODMODE='1'``
    must also open the gate. Operators paste-format their .env
    inconsistently; the gate honoring whatever the parser yields
    keeps the contract clean."""
    import athena.env as env_mod

    dotenv = tmp_path / ".env"
    dotenv.write_text('ATHENA_ALLOW_GODMODE="1"\n', encoding="utf-8")
    monkeypatch.setattr(env_mod, "_path", lambda: dotenv)
    env_mod.reset_cache()
    monkeypatch.delenv("ATHENA_ALLOW_GODMODE", raising=False)

    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "list")
    assert _captured_ui["warn"]
    assert any("og_godmode" in p for p in _captured_ui["print"])


def test_dotenv_wrong_value_does_not_open_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """Strict ``"1"`` match still applies to dotenv values --
    ``ATHENA_ALLOW_GODMODE=true`` in .env is NOT enough. The dotenv
    routing must not loosen the env-var contract; it just adds a
    second source for the same exact value."""
    import athena.env as env_mod

    dotenv = tmp_path / ".env"
    dotenv.write_text("ATHENA_ALLOW_GODMODE=true\n", encoding="utf-8")
    monkeypatch.setattr(env_mod, "_path", lambda: dotenv)
    env_mod.reset_cache()
    monkeypatch.delenv("ATHENA_ALLOW_GODMODE", raising=False)

    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "list")
    assert _captured_ui["error"], "expected refusal -- 'true' is not '1'"


def test_refusal_message_mentions_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    _agent: SimpleNamespace,
    _captured_ui: dict[str, list[str]],
) -> None:
    """The refusal message must point at BOTH the dotenv file and
    the shell env var so operators know either path works."""
    monkeypatch.delenv("ATHENA_ALLOW_GODMODE", raising=False)
    from athena.commands.godmode import cmd_godmode

    cmd_godmode(_agent, "list")
    combined = " ".join(_captured_ui["error"]).lower()
    assert ".env" in combined
    assert "athena_allow_godmode" in combined


# ---------------------------------------------------------------------------
# Help text + registration drift -- /godmode is a citizen of the
# slash registry
# ---------------------------------------------------------------------------


def test_godmode_in_slash_help() -> None:
    """``/help`` advertises godmode (with the gate marker) so an
    operator who runs ``/help`` and sees the entry can decide
    whether to opt in."""
    from athena.commands.help import SLASH_HELP

    assert "/godmode" in SLASH_HELP
    assert "ATHENA_ALLOW_GODMODE" in SLASH_HELP
