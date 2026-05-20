"""Tests for the Diagnose tool surface (T5-03R.2)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from athena.lsp.client import Diagnostic, Severity
from athena.tools.diagnose import Diagnose, diagnose_paths, format_summary


def _cfg(**overrides) -> Any:
    base = SimpleNamespace(
        lsp_enabled=True,
        lsp_server_command={"python": ["fake-server"]},
        lsp_timeout_s=30.0,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _err(path: str = "a.py", line: int = 1, col: int = 1, msg: str = "bad") -> Diagnostic:
    return Diagnostic(
        path=path,
        line=line,
        col=col,
        severity=Severity.ERROR,
        code="reportError",
        message=msg,
    )


def _warn(path: str = "a.py", msg: str = "meh") -> Diagnostic:
    return Diagnostic(
        path=path,
        line=2,
        col=3,
        severity=Severity.WARNING,
        code="reportWarn",
        message=msg,
    )


def _info(path: str = "a.py", msg: str = "fyi") -> Diagnostic:
    return Diagnostic(
        path=path,
        line=3,
        col=1,
        severity=Severity.INFORMATION,
        code="reportInfo",
        message=msg,
    )


# ---------------------------------------------------------------------------
# format_summary — the rendering contract
# ---------------------------------------------------------------------------


def test_format_summary_empty_ok(monkeypatch) -> None:
    """No diagnostics + LSP disabled → 'no diagnostics — LSP disabled'."""
    monkeypatch.setattr(
        "athena.tools.diagnose.load_config",
        lambda: _cfg(lsp_enabled=False),
    )
    out = format_summary(["a.py"], [])
    assert "LSP disabled" in out


def test_format_summary_clean_paths_report_ok(monkeypatch, tmp_path: Path) -> None:
    """LSP enabled + server on PATH + no diagnostics → 'N file(s) clean'."""
    monkeypatch.setattr(
        "athena.tools.diagnose.load_config",
        lambda: _cfg(),
    )
    monkeypatch.setattr(
        "athena.lsp.client.shutil.which",
        lambda _: "/usr/bin/fake-server",
    )
    py = tmp_path / "x.py"
    py.write_text("x = 1\n", encoding="utf-8")
    out = format_summary([str(py)], [])
    assert "clean" in out


def test_format_summary_no_server_installed(monkeypatch) -> None:
    """LSP enabled but no server installed → distinct ok message."""
    monkeypatch.setattr(
        "athena.tools.diagnose.load_config",
        lambda: _cfg(),
    )
    monkeypatch.setattr("athena.lsp.client.shutil.which", lambda _: None)
    out = format_summary(["a.py"], [])
    assert "not installed" in out


def test_errors_listed_first() -> None:
    diags = [
        _warn(msg="warn-1"),
        _info(msg="info-1"),
        _err(msg="error-1"),
        _err(msg="error-2"),
        _warn(msg="warn-2"),
    ]
    out = format_summary(["a.py"], diags)
    # Errors come before warnings come before info.
    err1 = out.index("error-1")
    err2 = out.index("error-2")
    warn1 = out.index("warn-1")
    warn2 = out.index("warn-2")
    info1 = out.index("info-1")
    assert err1 < warn1
    assert err2 < warn1
    assert warn1 < info1
    assert warn2 < info1


def test_summary_header_counts() -> None:
    diags = [_err(), _err(), _warn(), _info()]
    out = format_summary(["a.py"], diags)
    first_line = out.splitlines()[0]
    assert "2 errors" in first_line
    assert "1 warning" in first_line
    assert "1 info" in first_line


def test_summary_header_singular() -> None:
    diags = [_err()]
    out = format_summary(["a.py"], diags)
    first_line = out.splitlines()[0]
    assert "1 error" in first_line
    assert "errors" not in first_line  # singular only


def test_summary_emits_path_line_col_code_message() -> None:
    diags = [_err(path="foo.py", line=42, col=7, msg="missing import")]
    out = format_summary(["foo.py"], diags)
    body = out.splitlines()[1]
    assert "foo.py:42:7" in body
    assert "[error]" in body
    assert "reportError" in body
    assert "missing import" in body


def test_summary_truncates_at_200(monkeypatch) -> None:
    diags = [_err(line=i + 1, msg=f"err-{i}") for i in range(250)]
    out = format_summary(["a.py"], diags)
    body_lines = out.splitlines()[1:]
    # 200 diagnostic lines + one truncation marker.
    assert len(body_lines) == 201
    assert "truncated" in body_lines[-1]
    assert "+50" in body_lines[-1]


# ---------------------------------------------------------------------------
# Diagnose tool wrapper
# ---------------------------------------------------------------------------


def test_tool_requires_paths() -> None:
    """No paths kwarg → tool returns an ERROR string (model-friendly)."""
    assert Diagnose(paths=[]) == "ERROR: paths required"
    assert Diagnose(paths=None) == "ERROR: paths required"
    assert Diagnose() == "ERROR: paths required"


def test_tool_returns_summary(monkeypatch, tmp_path: Path) -> None:
    """Happy path: tool calls the client, then format_summary."""
    py = tmp_path / "x.py"
    py.write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        "athena.tools.diagnose.load_config",
        lambda: _cfg(),
    )
    monkeypatch.setattr(
        "athena.tools.diagnose.diagnose",
        lambda paths, *, cfg: [
            _err(path=str(py), line=10, col=5, msg="boom"),
        ],
    )
    monkeypatch.setattr(
        "athena.lsp.client.shutil.which",
        lambda _: "/usr/bin/fake-server",
    )

    out = Diagnose(paths=[str(py)])
    assert "1 error" in out
    assert ":10:5" in out
    assert "boom" in out


def test_tool_clean_paths_report_ok(monkeypatch, tmp_path: Path) -> None:
    py = tmp_path / "x.py"
    py.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr("athena.tools.diagnose.load_config", lambda: _cfg())
    monkeypatch.setattr("athena.tools.diagnose.diagnose", lambda paths, *, cfg: [])
    monkeypatch.setattr(
        "athena.lsp.client.shutil.which",
        lambda _: "/usr/bin/fake-server",
    )
    out = Diagnose(paths=[str(py)])
    assert "clean" in out


def test_tool_handles_client_exception(monkeypatch, tmp_path: Path) -> None:
    """The client is graceful by design, but defensive: if it ever
    raises, the tool surface swallows + returns the 'ok' string."""
    py = tmp_path / "x.py"
    py.write_text("x = 1\n", encoding="utf-8")

    def _boom(_paths, *, cfg):  # noqa: D401
        raise RuntimeError("client melted")

    monkeypatch.setattr("athena.tools.diagnose.load_config", lambda: _cfg())
    monkeypatch.setattr("athena.tools.diagnose.diagnose", _boom)
    monkeypatch.setattr(
        "athena.lsp.client.shutil.which",
        lambda _: "/usr/bin/fake-server",
    )

    out = Diagnose(paths=[str(py)])
    # No exception escapes; 'ok' lands because diagnostics list is empty.
    assert "error" not in out.lower() or "[error]" not in out
    assert "clean" in out or "no diagnostics" in out


def test_diagnose_paths_alias_callable(monkeypatch, tmp_path: Path) -> None:
    """T5-04 verifier consumes diagnose_paths(paths) directly.
    The alias must produce the same Diagnostic list the client
    produces — no transformation."""
    py = tmp_path / "x.py"
    py.write_text("x = 1\n", encoding="utf-8")
    fake_diags = [_err(path=str(py), msg="t5-04 saw this")]

    monkeypatch.setattr("athena.tools.diagnose.load_config", lambda: _cfg())
    monkeypatch.setattr(
        "athena.tools.diagnose.diagnose",
        lambda paths, *, cfg: fake_diags,
    )

    assert diagnose_paths([str(py)]) == fake_diags


# ---------------------------------------------------------------------------
# Registry hookup
# ---------------------------------------------------------------------------


def test_diagnose_tool_registered() -> None:
    """The @tool decorator runs at import time. Confirm the name
    + alias are reachable through the registry."""
    from athena.tools.registry import get_tool

    by_name = get_tool("Diagnose")
    by_alias = get_tool("diagnose")
    assert by_name is not None
    assert by_alias is not None
    assert by_name is by_alias
    assert by_name.toolset == "code"
