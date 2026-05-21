"""T7-01.2 — CLI integration tests for the new headless flags.

Tests the path through __main__.py + run_headless together
without booting a real model. The Agent is stubbed; the rest
of the CLI plumbing (argparse, --json envelope to stdout,
TTY chatter to stderr, exit code mapping, --task FILE
reading) is exercised end-to-end.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


# ---------------------------------------------------------------
# In-process tests — call main() directly with a stub Agent
# injected into run_headless via monkeypatch
# ---------------------------------------------------------------


class _Stats:
    def __init__(self, **kw):
        self.prompt_tokens = kw.get("prompt", 10)
        self.eval_tokens = kw.get("eval", 5)
        self.cache_read_tokens = 0
        self.cache_creation_tokens = 0
        self.tool_call_counts = dict(kw.get("tool_call_counts", {}))


class _StubAgent:
    """Mirrors the minimal interface __main__.py + run_headless
    read off the agent — model + session_id + stats + _last_assistant_text
    + run_turn + close."""

    def __init__(
        self, cfg: Any, workspace: Path,
        model: str | None = None,
        *,
        assistant_text: str = "answer from stub",
        raise_on_run_turn: Exception | None = None,
        **_kw: Any,
    ):
        self.cfg = cfg
        self.workspace = workspace
        self.model = model or getattr(cfg, "model", "stub-model")
        self.session_id = "s-cli-1"
        self._last_assistant_text = assistant_text
        self.stats = _Stats()
        self._raise = raise_on_run_turn
        self._closed = False

    @property
    def provider(self):
        """Mimic the provider sanity-check from __main__: must
        have a list_models() that returns something so the
        "cannot reach Ollama" branch doesn't fire."""
        return SimpleNamespace(list_models=lambda: [self.model])

    def run_turn(self, task: str) -> None:
        if self._raise is not None:
            raise self._raise

    def close(self) -> None:
        self._closed = True


@pytest.fixture
def stub_main_env(monkeypatch, tmp_path: Path):
    """Patch the CLI's heavy dependencies so main() runs in
    isolation:
      - Agent → _StubAgent (no Ollama, no MCP load needed)
      - load_mcp_servers → no-op
      - shutdown_all → no-op
      - CONFIG_DIR / SESSIONS_DIR redirected to tmp_path
      - profile_dir → tmp_path
    """
    # Athena module imports.
    import athena.__main__ as cli
    import athena.headless.runner as runner_mod

    monkeypatch.setattr(cli, "Agent", _StubAgent)
    monkeypatch.setattr(cli, "load_mcp_servers", lambda *a, **kw: None)
    monkeypatch.setattr(cli, "shutdown_all", lambda: None)

    # Redirect athena's per-profile data to tmp.
    monkeypatch.setattr(cli, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(cli, "SESSIONS_DIR", tmp_path / "sessions")
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "sessions").mkdir(exist_ok=True)

    # Workspace argument resolution uses Path.cwd() when -C not
    # passed; pin it to tmp so the workspace.is_dir() check passes.
    monkeypatch.chdir(tmp_path)

    # Track stderr capture
    captured = {"stderr": [], "stdout": []}

    def _capture_stderr(*args, **kwargs):
        text = " ".join(str(a) for a in args)
        captured["stderr"].append(text)

    # Reroute ui.error/warn/info/banner to capture lists so the
    # test can assert what was emitted where.
    import athena.ui as ui_mod
    monkeypatch.setattr(ui_mod, "error", _capture_stderr)
    monkeypatch.setattr(ui_mod, "warn", _capture_stderr)
    monkeypatch.setattr(ui_mod, "info", _capture_stderr)
    monkeypatch.setattr(ui_mod, "banner", lambda *a, **kw: None)

    return SimpleNamespace(
        captured=captured,
        cli=cli,
        runner_mod=runner_mod,
        tmp_path=tmp_path,
    )


def _run_main(argv: list[str], env: Any, capsys) -> tuple[int, str, str]:
    """Set sys.argv to argv, call main(), capture stdout+stderr.
    Returns (exit_code, stdout, stderr)."""
    import sys as _sys
    saved = _sys.argv
    _sys.argv = ["athena", *argv]
    try:
        exit_code = env.cli.main()
    finally:
        _sys.argv = saved
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# ---------------------------------------------------------------
# Argument parsing — new flags accepted
# ---------------------------------------------------------------


def test_argparse_accepts_json_flag(stub_main_env, capsys):
    code, out, _err = _run_main(
        ["-p", "hello", "--json"], stub_main_env, capsys,
    )
    # JSON mode → envelope on stdout, exit 0 on success.
    assert code == 0
    # Single line on stdout.
    payload = json.loads(out.strip())
    assert payload["status"] == "ok"


def test_argparse_accepts_run_id(stub_main_env, capsys):
    code, out, _err = _run_main(
        ["-p", "hello", "--json", "--run-id", "r-batch-42"],
        stub_main_env, capsys,
    )
    assert code == 0
    payload = json.loads(out.strip())
    assert payload["run_id"] == "r-batch-42"


def test_argparse_accepts_timeout(stub_main_env, capsys):
    """Smoke: --timeout parses as a float and the run still
    completes (the stub agent doesn't actually wait)."""
    code, _out, _err = _run_main(
        ["-p", "hello", "--timeout", "30.0"],
        stub_main_env, capsys,
    )
    assert code == 0


# ---------------------------------------------------------------
# --json envelope shape + clean stdout
# ---------------------------------------------------------------


def test_json_envelope_is_single_line(stub_main_env, capsys):
    code, out, _err = _run_main(
        ["-p", "hello", "--json"], stub_main_env, capsys,
    )
    assert code == 0
    # Strip trailing newline, count internal newlines.
    body = out.rstrip("\n")
    assert "\n" not in body  # single line


def test_json_envelope_parsable(stub_main_env, capsys):
    code, out, _err = _run_main(
        ["-p", "hello", "--json"], stub_main_env, capsys,
    )
    assert code == 0
    payload = json.loads(out.strip())
    assert set(payload.keys()) >= {
        "run_id", "status", "exit_code",
        "started_at", "finished_at", "duration_s",
        "task", "workspace", "model", "profile",
        "session_id", "tool_calls", "tokens",
        "cost_est", "assistant_text", "error",
    }


def test_json_mode_no_envelope_chatter_on_stdout(stub_main_env, capsys):
    """The only thing on stdout in JSON mode is the envelope.
    No banner, no progress, no model output line — those go
    to stderr (or to wherever the agent's own run_turn writes
    them, but specifically NOT to stdout)."""
    code, out, _err = _run_main(
        ["-p", "hello", "--json"], stub_main_env, capsys,
    )
    assert code == 0
    # First non-empty line on stdout should be valid JSON.
    first_line = next(l for l in out.splitlines() if l.strip())
    parsed = json.loads(first_line)
    assert parsed["status"] == "ok"


# ---------------------------------------------------------------
# --task FILE reading
# ---------------------------------------------------------------


def test_task_from_file(stub_main_env, capsys, tmp_path: Path):
    task_file = tmp_path / "long_task.txt"
    task_file.write_text(
        "this is a long prompt\nwith multiple lines\nand 'quotes' \"too\"",
        encoding="utf-8",
    )
    code, out, _err = _run_main(
        ["--task", str(task_file), "--json"],
        stub_main_env, capsys,
    )
    assert code == 0
    payload = json.loads(out.strip())
    assert payload["status"] == "ok"
    assert "multiple lines" in payload["task"]
    assert "'quotes'" in payload["task"]


def test_task_file_missing_invalid(stub_main_env, capsys, tmp_path: Path):
    code, out, _err = _run_main(
        ["--task", str(tmp_path / "nonexistent.txt"), "--json"],
        stub_main_env, capsys,
    )
    assert code == 2
    payload = json.loads(out.strip())
    assert payload["status"] == "invalid"
    assert "not found" in payload["error"]


def test_task_file_wins_over_prompt(stub_main_env, capsys, tmp_path: Path):
    task_file = tmp_path / "t.txt"
    task_file.write_text("from-file task", encoding="utf-8")
    code, out, _err = _run_main(
        ["-p", "from-inline-prompt", "--task", str(task_file), "--json"],
        stub_main_env, capsys,
    )
    assert code == 0
    payload = json.loads(out.strip())
    # The --task content wins.
    assert payload["task"] == "from-file task"


# ---------------------------------------------------------------
# --json without -p / --task is invalid
# ---------------------------------------------------------------


def test_json_without_task_invalid(stub_main_env, capsys):
    code, out, _err = _run_main(
        ["--json"], stub_main_env, capsys,
    )
    assert code == 2
    payload = json.loads(out.strip())
    assert payload["status"] == "invalid"
    assert "requires a task" in payload["error"]


# ---------------------------------------------------------------
# Exit code on error path
# ---------------------------------------------------------------


def test_error_in_run_turn_exits_with_1(stub_main_env, capsys, monkeypatch):
    """When the agent's run_turn raises, the envelope reports
    status=error and the dispatcher exits 1."""
    # Re-patch Agent to one that raises.
    def _failing_agent(*a, **kw):
        return _StubAgent(*a, raise_on_run_turn=RuntimeError("model dead"), **kw)
    monkeypatch.setattr(stub_main_env.cli, "Agent", _failing_agent)

    code, out, _err = _run_main(
        ["-p", "hello", "--json"], stub_main_env, capsys,
    )
    assert code == 1
    payload = json.loads(out.strip())
    assert payload["status"] == "error"
    assert "model dead" in payload["error"]


# ---------------------------------------------------------------
# Backwards-compatible legacy -p path
# ---------------------------------------------------------------


def test_legacy_dash_p_still_returns_zero_on_success(stub_main_env, capsys):
    """The existing `athena -p "<task>"` behavior is preserved:
    exit 0 on success, no JSON envelope on stdout."""
    code, out, _err = _run_main(["-p", "hello"], stub_main_env, capsys)
    assert code == 0
    # No JSON envelope on stdout — backwards-compatible mode.
    if out.strip():
        with pytest.raises(json.JSONDecodeError):
            json.loads(out.strip().splitlines()[0])
