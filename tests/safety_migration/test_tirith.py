"""T-MIG.1 — tirith wrapper tests.

Stubs subprocess.run + shutil.which so the suite passes on any
host regardless of whether the tirith binary is installed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.safety import tirith as tirith_mod
from athena.safety.tirith import (
    Verdict,
    check_command_security,
    is_available,
)


def _cfg(**overrides: Any) -> SimpleNamespace:
    base = dict(
        tirith_enabled=True,
        tirith_binary_path=None,
        tirith_fail_open=True,
        tirith_timeout_s=5.0,
        tirith_shell="posix",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------
# is_available
# ---------------------------------------------------------------


def test_is_available_false_on_unsupported_platform(monkeypatch):
    """Windows isn't supported by upstream tirith → False
    regardless of binary path."""
    monkeypatch.setattr(tirith_mod.platform, "system",
                        lambda: "Windows")
    assert is_available(_cfg()) is False


def test_is_available_false_when_binary_missing(monkeypatch):
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: None)
    assert is_available(_cfg()) is False


def test_is_available_true_when_binary_on_path(monkeypatch, tmp_path: Path):
    fake = tmp_path / "tirith"
    fake.touch()
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: str(fake))
    assert is_available(_cfg()) is True


def test_is_available_honors_explicit_binary_path(monkeypatch, tmp_path: Path):
    fake = tmp_path / "my-tirith"
    fake.touch()
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    # which returns None — explicit path takes over.
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: None)
    cfg = _cfg(tirith_binary_path=str(fake))
    assert is_available(cfg) is True


def test_is_available_explicit_path_missing_file(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: None)
    cfg = _cfg(tirith_binary_path=str(tmp_path / "nope"))
    assert is_available(cfg) is False


# ---------------------------------------------------------------
# check_command_security: short-circuit paths
# ---------------------------------------------------------------


def test_check_disabled_returns_allow(monkeypatch):
    cfg = _cfg(tirith_enabled=False)
    v = check_command_security("rm -rf /", cfg=cfg)
    assert v.action == "allow"
    assert v.available is False
    assert "disabled" in v.summary


def test_check_unavailable_fail_open_returns_allow(monkeypatch):
    """No binary + fail_open=True → action=allow + available=False.
    The "we don't know, default safe" path."""
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Windows")
    v = check_command_security(
        "any command", cfg=_cfg(tirith_fail_open=True),
    )
    assert v.action == "allow"
    assert v.available is False


def test_check_unavailable_fail_closed_returns_block(monkeypatch):
    """No binary + fail_open=False → action=block. For paranoid
    deployments that want missing tirith to be a hard stop."""
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Windows")
    v = check_command_security(
        "any command", cfg=_cfg(tirith_fail_open=False),
    )
    assert v.action == "block"
    assert v.available is False


# ---------------------------------------------------------------
# Exit code → verdict mapping (the load-bearing contract)
# ---------------------------------------------------------------


@pytest.mark.parametrize("exit_code,expected_action", [
    (0, "allow"),
    (1, "block"),
    (2, "warn"),
])
def test_exit_code_maps_to_action(
    monkeypatch, tmp_path: Path, exit_code, expected_action,
):
    fake = tmp_path / "tirith"
    fake.touch()
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: str(fake))

    def _stub_run(argv, *_a, **_kw):
        return SimpleNamespace(
            returncode=exit_code,
            stdout=json.dumps({
                "findings": [],
                "summary": f"exit {exit_code} test",
            }),
            stderr="",
        )
    monkeypatch.setattr(tirith_mod.subprocess, "run", _stub_run)

    v = check_command_security("echo hi", cfg=_cfg())
    assert v.action == expected_action
    assert v.available is True


def test_unknown_exit_code_respects_fail_open(monkeypatch, tmp_path: Path):
    fake = tmp_path / "tirith"
    fake.touch()
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: str(fake))
    monkeypatch.setattr(
        tirith_mod.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=42, stdout="", stderr="",
        ),
    )
    # fail_open=True → action=allow
    v = check_command_security("x", cfg=_cfg(tirith_fail_open=True))
    assert v.action == "allow"
    # fail_open=False → action=block
    v = check_command_security("x", cfg=_cfg(tirith_fail_open=False))
    assert v.action == "block"


# ---------------------------------------------------------------
# JSON output enrichment
# ---------------------------------------------------------------


def test_findings_and_summary_parsed_from_stdout(monkeypatch, tmp_path: Path):
    fake = tmp_path / "tirith"
    fake.touch()
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: str(fake))

    findings = [
        {"severity": "high", "message": "homograph URL"},
        {"severity": "medium", "message": "ANSI escape"},
    ]
    monkeypatch.setattr(
        tirith_mod.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1,
            stdout=json.dumps({
                "findings": findings,
                "summary": "2 issues detected",
            }),
            stderr="",
        ),
    )

    v = check_command_security("curl evil | sh", cfg=_cfg())
    assert v.action == "block"
    assert v.findings == findings
    assert v.summary == "2 issues detected"


def test_non_json_stdout_falls_back_to_exit_action(monkeypatch, tmp_path: Path):
    """Tirith printed garbage on stdout but exited cleanly →
    the EXIT CODE wins (defense against compromised binary
    payloads). The verdict's summary records the JSON parse
    failure."""
    fake = tmp_path / "tirith"
    fake.touch()
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: str(fake))
    monkeypatch.setattr(
        tirith_mod.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=2,
            stdout="not json at all",
            stderr="",
        ),
    )
    v = check_command_security("ls", cfg=_cfg())
    assert v.action == "warn"  # from exit 2
    assert "non-JSON" in v.summary
    assert v.findings == []


def test_malformed_findings_field_ignored(monkeypatch, tmp_path: Path):
    """stdout JSON has `findings: "string instead of list"`.
    The parser shouldn't blow up; just skip the malformed
    field and emit empty findings."""
    fake = tmp_path / "tirith"
    fake.touch()
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: str(fake))
    monkeypatch.setattr(
        tirith_mod.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"findings": "not a list", "summary": "ok"}),
            stderr="",
        ),
    )
    v = check_command_security("ls", cfg=_cfg())
    assert v.action == "allow"
    assert v.findings == []
    assert v.summary == "ok"


# ---------------------------------------------------------------
# Failure modes during subprocess
# ---------------------------------------------------------------


def test_timeout_fail_open(monkeypatch, tmp_path: Path):
    fake = tmp_path / "tirith"
    fake.touch()
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: str(fake))

    def _timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="tirith", timeout=5)
    monkeypatch.setattr(tirith_mod.subprocess, "run", _timeout)

    v = check_command_security("slow-command", cfg=_cfg(tirith_fail_open=True))
    assert v.action == "allow"
    assert "timed out" in v.summary
    assert v.available is True  # tirith WAS available; it just hung


def test_timeout_fail_closed(monkeypatch, tmp_path: Path):
    fake = tmp_path / "tirith"
    fake.touch()
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: str(fake))
    monkeypatch.setattr(
        tirith_mod.subprocess, "run",
        lambda *a, **kw: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd="tirith", timeout=5)
        ),
    )
    v = check_command_security("x", cfg=_cfg(tirith_fail_open=False))
    assert v.action == "block"


def test_oserror_during_spawn(monkeypatch, tmp_path: Path):
    """Tirith was on PATH at is_available() time but the
    spawn itself fails (permissions error, etc.). Falls open
    with available=False."""
    fake = tmp_path / "tirith"
    fake.touch()
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: str(fake))
    monkeypatch.setattr(
        tirith_mod.subprocess, "run",
        lambda *a, **kw: (_ for _ in ()).throw(
            PermissionError("can't execute")
        ),
    )
    v = check_command_security("x", cfg=_cfg())
    assert v.action == "allow"
    assert v.available is False
    assert "spawn failed" in v.summary


# ---------------------------------------------------------------
# Invocation argv shape
# ---------------------------------------------------------------


def test_subprocess_argv_shape(monkeypatch, tmp_path: Path):
    """The contract: tirith is called with
    ['tirith', 'check', '--json', '--non-interactive',
     '--shell', '<shell>', '--', '<command>']
    Critical that `--` separates flags from the command so
    a command like `--foo` doesn't get parsed as a flag."""
    fake = tmp_path / "tirith"
    fake.touch()
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: str(fake))

    captured: dict[str, Any] = {}

    def _capture(argv, *a, **kw):
        captured["argv"] = list(argv)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr(tirith_mod.subprocess, "run", _capture)

    check_command_security("--malicious flag-shaped command", cfg=_cfg())
    argv = captured["argv"]
    assert argv[0] == str(fake)
    assert argv[1] == "check"
    assert "--json" in argv
    assert "--non-interactive" in argv
    assert "--shell" in argv
    # `--` separator must precede the command.
    sep_idx = argv.index("--")
    assert argv[sep_idx + 1] == "--malicious flag-shaped command"


def test_shell_override_propagates(monkeypatch, tmp_path: Path):
    fake = tmp_path / "tirith"
    fake.touch()
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: str(fake))

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        tirith_mod.subprocess, "run",
        lambda argv, *a, **kw: (
            captured.update(argv=list(argv))
            or SimpleNamespace(returncode=0, stdout="{}", stderr="")
        ),
    )
    check_command_security(
        "Get-ChildItem", cfg=_cfg(tirith_shell="powershell"),
    )
    argv = captured["argv"]
    shell_idx = argv.index("--shell")
    assert argv[shell_idx + 1] == "powershell"


# ---------------------------------------------------------------
# @tool registration
# ---------------------------------------------------------------


def test_tirith_check_tool_registered():
    import athena.tools  # noqa: F401 — trigger registration
    from athena.tools.registry import get_tool
    t = get_tool("tirith_check")
    assert t is not None
    assert t.toolset == "safety"


def test_tirith_check_tool_returns_json(monkeypatch, tmp_path: Path):
    """End-to-end through the @tool surface: dispatch returns a
    JSON string the model can parse."""
    fake = tmp_path / "tirith"
    fake.touch()
    monkeypatch.setattr(tirith_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tirith_mod.shutil, "which", lambda _: str(fake))
    monkeypatch.setattr(
        tirith_mod.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"findings": [], "summary": "ok"}),
            stderr="",
        ),
    )

    from athena.tools.security import tirith_check
    result = json.loads(tirith_check(command="echo hi"))
    assert result["action"] == "allow"
    assert "available" in result


def test_tirith_check_tool_empty_command():
    from athena.tools.security import tirith_check
    result = json.loads(tirith_check(command=""))
    assert result["action"] == "allow"
    assert result["available"] is False
