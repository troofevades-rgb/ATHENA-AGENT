"""``/status`` surfaces godmode session state.

Phase 2 follow-up. Until 0.3.0, an operator who wanted to know if
the active session was jailbroken had to run ``/godmode list`` and
look for the ``(active)`` marker. After this commit ``/status``
shows it directly:

    godmode:
      active:   boundary_inversion  (mode=system_prompt)
      since:    2026-05-30T10:15:22+00:00
      prefill:  /home/user/.athena/skills/godmode/templates/prefill.json

Pins:

  * ``cmd_status`` reads ``agent._active_godmode`` and
    ``agent.cfg.agent_prefill_messages_file`` and pushes them into
    the snapshot.
  * ``render_status`` shows the godmode block only when either is
    set -- a fresh / unjailbroken session's /status stays clean
    (no phantom block).
  * Both ``system_prompt`` and ``steer`` modes render.
  * Prefill file alone (no apply) still shows the block (operators
    can use prefill independently of system-prompt mutation).
"""

from __future__ import annotations

from athena.cli.status import render_status


def _base_snapshot() -> dict:
    return {
        "session_id": "s",
        "model": "qwen",
        "provider": "ollama",
        "profile": "default",
        "elapsed_seconds": 10.0,
        "turns": 0,
        "tool_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def test_render_omits_godmode_block_when_nothing_active() -> None:
    out = render_status(_base_snapshot())
    assert "godmode:" not in out


def test_render_shows_godmode_block_with_system_prompt_mode() -> None:
    snap = _base_snapshot()
    snap["godmode"] = {
        "strategy": "boundary_inversion",
        "mode": "system_prompt",
        "applied_at": "2026-05-30T10:15:22+00:00",
    }
    out = render_status(snap)
    assert "godmode:" in out
    assert "boundary_inversion" in out
    assert "system_prompt" in out
    assert "2026-05-30" in out


def test_render_shows_godmode_block_with_steer_mode() -> None:
    snap = _base_snapshot()
    snap["godmode"] = {
        "strategy": "og_godmode",
        "mode": "steer",
        "applied_at": "2026-05-30T11:00:00+00:00",
    }
    out = render_status(snap)
    assert "godmode:" in out
    assert "og_godmode" in out
    assert "steer" in out


def test_render_shows_prefill_file_alone() -> None:
    """Operators can set a prefill file without applying a strategy
    -- the status block still appears so they know prefill is on."""
    snap = _base_snapshot()
    snap["godmode_prefill_file"] = "/home/user/.athena/godmode/prefill.json"
    out = render_status(snap)
    assert "godmode:" in out
    assert "prefill:" in out
    assert "/home/user/.athena/godmode/prefill.json" in out


def test_render_shows_active_and_prefill_together() -> None:
    snap = _base_snapshot()
    snap["godmode"] = {
        "strategy": "default",
        "mode": "system_prompt",
        "applied_at": "2026-05-30T11:00:00+00:00",
    }
    snap["godmode_prefill_file"] = "/path/to/prefill.json"
    out = render_status(snap)
    assert "godmode:" in out
    assert "default" in out
    assert "/path/to/prefill.json" in out


# ---------------------------------------------------------------------------
# cmd_status integration -- the slash command reads agent state
# correctly into the snapshot
# ---------------------------------------------------------------------------


def test_cmd_status_pushes_active_godmode_into_snapshot(
    monkeypatch,
) -> None:
    """``cmd_status`` reads ``agent._active_godmode`` + the prefill
    config knob and adds them to the snapshot before rendering."""
    from types import SimpleNamespace

    import athena.commands.status as st

    captured: dict = {}

    def _fake_render(snap: dict) -> str:
        captured["snap"] = snap
        return ""

    monkeypatch.setattr(st, "render_status", _fake_render, raising=False)
    # Patch the import-time symbol the command uses; render_status
    # is imported lazily so we patch the module the function
    # imports from.
    import athena.cli.status as cli_st

    monkeypatch.setattr(cli_st, "render_status", _fake_render)

    class _FakeStats:
        prompt_tokens = 0
        eval_tokens = 0

        def to_snapshot(self, **kw):
            return {**kw, "model": "qwen", "provider": "ollama", "profile": "default"}

    agent = SimpleNamespace(
        stats=_FakeStats(),
        session_id="s",
        model="qwen",
        provider=SimpleNamespace(name="ollama"),
        cfg=SimpleNamespace(
            profile="default",
            cache_strategy=None,
            prompt_cache_ttl=None,
            agent_prefill_messages_file="/path/to/prefill.json",
        ),
        _active_godmode={
            "strategy": "og_godmode",
            "mode": "system_prompt",
            "applied_at": "2026-05-30T12:00:00+00:00",
        },
    )

    # Silence ui.console.print which the cmd calls.
    monkeypatch.setattr(st.ui.console, "print", lambda *a, **kw: None)

    st.cmd_status(agent, "")

    snap = captured["snap"]
    assert snap.get("godmode") == {
        "strategy": "og_godmode",
        "mode": "system_prompt",
        "applied_at": "2026-05-30T12:00:00+00:00",
    }
    assert snap.get("godmode_prefill_file") == "/path/to/prefill.json"
