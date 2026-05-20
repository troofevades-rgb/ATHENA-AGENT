"""Tests for the ``athena verify`` one-shot CLI (T5-04.4)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.cli import verify as cli_verify
from athena.verify.outcome import VerificationOutcome


def _cfg(**overrides) -> SimpleNamespace:
    base = {
        "verify_on_write": "diagnose",
        "verify_command": None,
        "verify_auto_rollback": False,
        "verify_auto_retry": False,
        "verify_max_retries": 2,
        "verify_run_timeout_s": 30.0,
        "sandbox_enabled": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def passing_verifier(monkeypatch):
    class _P:
        def __init__(self, **kw):
            pass

        def verify_write(self, p):
            return VerificationOutcome(path=str(p), outcome="passed")

    monkeypatch.setattr(cli_verify, "VerifiedExecution", _P)
    monkeypatch.setattr(cli_verify, "load_config", lambda: _cfg())


def test_missing_path_exits_3(tmp_path, capsys):
    rc = cli_verify.main([str(tmp_path / "does_not_exist.py")])
    err = capsys.readouterr().err
    assert rc == 3
    assert "does not exist" in err


def test_passing_returns_zero(tmp_path, passing_verifier, capsys):
    target = tmp_path / "ok.py"
    target.write_text("x = 1\n")
    rc = cli_verify.main([str(target)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "verified" in out


def test_failed_diagnostics_returns_one(tmp_path, monkeypatch, capsys):
    class _Fail:
        def __init__(self, **kw):
            pass

        def verify_write(self, p):
            return VerificationOutcome(
                path=str(p),
                outcome="failed_diagnostics",
                introduced_errors=["boom"],
            )

    monkeypatch.setattr(cli_verify, "VerifiedExecution", _Fail)
    monkeypatch.setattr(cli_verify, "load_config", lambda: _cfg())

    target = tmp_path / "x.py"
    target.write_text("x = 1\n")
    rc = cli_verify.main([str(target)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "boom" in out


def test_failed_run_returns_two(tmp_path, monkeypatch, capsys):
    class _Fail:
        def __init__(self, **kw):
            pass

        def verify_write(self, p):
            return VerificationOutcome(
                path=str(p),
                outcome="failed_run",
                run_exit_code=2,
                run_stderr_tail="pytest blew up",
            )

    monkeypatch.setattr(cli_verify, "VerifiedExecution", _Fail)
    monkeypatch.setattr(cli_verify, "load_config", lambda: _cfg())

    target = tmp_path / "x.py"
    target.write_text("x = 1\n")
    rc = cli_verify.main([str(target)])
    out = capsys.readouterr().out
    assert rc == 2
    assert "pytest blew up" in out


def test_command_flag_forces_run_mode(tmp_path, monkeypatch, capsys):
    """``--command pytest -q`` must flip cfg.verify_on_write to
    "diagnose+run" and stash the command on cfg, regardless of
    the loaded config's defaults."""
    seen_cfgs: list = []

    class _Spy:
        def __init__(self, *, cfg, workspace=None, **kw):
            seen_cfgs.append(cfg)

        def verify_write(self, p):
            return VerificationOutcome(path=str(p), outcome="passed")

    # Start with diagnose-only config; --command should override.
    monkeypatch.setattr(cli_verify, "VerifiedExecution", _Spy)
    monkeypatch.setattr(
        cli_verify, "load_config", lambda: _cfg(verify_on_write="diagnose")
    )

    target = tmp_path / "x.py"
    target.write_text("x = 1\n")
    rc = cli_verify.main([str(target), "--command", "pytest -q"])
    assert rc == 0
    assert seen_cfgs[0].verify_command == "pytest -q"
    assert seen_cfgs[0].verify_on_write == "diagnose+run"


def test_no_sandbox_flag_disables_sandbox(tmp_path, monkeypatch):
    seen_cfgs: list = []

    class _Spy:
        def __init__(self, *, cfg, workspace=None, **kw):
            seen_cfgs.append(cfg)

        def verify_write(self, p):
            return VerificationOutcome(path=str(p), outcome="passed")

    monkeypatch.setattr(cli_verify, "VerifiedExecution", _Spy)
    monkeypatch.setattr(cli_verify, "load_config", lambda: _cfg(sandbox_enabled=True))

    target = tmp_path / "x.py"
    target.write_text("x = 1\n")
    cli_verify.main([str(target), "--no-sandbox"])
    assert seen_cfgs[0].sandbox_enabled is False
