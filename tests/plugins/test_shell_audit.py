"""Bundled shell_audit plugin: writes JSONL per session for shell tool calls."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_shell_audit_class():
    """Importlib the bundled plugin.py the same way the loader does."""
    plugin_py = (
        Path(__file__).resolve().parents[2]
        / "athena"
        / "plugins"
        / "bundled"
        / "shell_audit"
        / "plugin.py"
    )
    spec = importlib.util.spec_from_file_location("athena_plugin__shell_audit_test", plugin_py)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ShellAuditPlugin


@pytest.fixture
def plugin(tmp_path):
    cls = _load_shell_audit_class()
    p = cls(config={"log_root": str(tmp_path / "audit")})
    p.name = "shell_audit"
    return p


def test_writes_log_for_bash_tool(plugin, tmp_path):
    plugin.on_session_start("sess-123", "default")
    plugin.post_tool_call("Bash", {"command": "ls -la"}, "drwxr-xr-x ...")
    log_file = tmp_path / "audit" / "sess-123.jsonl"
    assert log_file.exists()
    line = log_file.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["tool"] == "Bash"
    assert record["args"] == {"command": "ls -la"}
    assert "timestamp" in record


def test_writes_log_for_lowercase_bash_alias(plugin, tmp_path):
    plugin.on_session_start("s1", "default")
    plugin.post_tool_call("bash", {"command": "pwd"}, "/tmp")
    log = (tmp_path / "audit" / "s1.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(log)["tool"] == "bash"


def test_ignores_non_shell_tools(plugin, tmp_path):
    plugin.on_session_start("s2", "default")
    plugin.post_tool_call("Read", {"path": "/tmp/x"}, "content")
    plugin.post_tool_call("Edit", {}, "ok")
    log_file = tmp_path / "audit" / "s2.jsonl"
    # File should NOT exist — no shell tools were called.
    assert not log_file.exists()


def test_log_path_under_session_id(plugin, tmp_path):
    plugin.on_session_start("aaa-bbb-ccc", "default")
    plugin.post_tool_call("shell", {}, "result")
    log_file = tmp_path / "audit" / "aaa-bbb-ccc.jsonl"
    assert log_file.exists()


def test_truncates_long_results(plugin, tmp_path):
    """Results longer than the truncation cap (500 chars) get truncated."""
    plugin.on_session_start("trunc", "default")
    huge = "x" * 5000
    plugin.post_tool_call("Bash", {"command": "yes"}, huge)
    log = (tmp_path / "audit" / "trunc.jsonl").read_text(encoding="utf-8").strip()
    record = json.loads(log)
    assert len(record["result_truncated"]) == 500


def test_no_op_when_session_start_not_fired(plugin, tmp_path):
    """post_tool_call before on_session_start must be safe (no log path yet)."""
    plugin.post_tool_call("Bash", {"command": "ls"}, "ok")
    # No file because no session_id; no exception either.
    audit_dir = tmp_path / "audit"
    assert not audit_dir.exists() or list(audit_dir.iterdir()) == []


def test_appends_across_multiple_calls(plugin, tmp_path):
    plugin.on_session_start("multi", "default")
    plugin.post_tool_call("Bash", {"command": "a"}, "r1")
    plugin.post_tool_call("Bash", {"command": "b"}, "r2")
    plugin.post_tool_call("Bash", {"command": "c"}, "r3")
    lines = (tmp_path / "audit" / "multi.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    commands = [json.loads(line)["args"]["command"] for line in lines]
    assert commands == ["a", "b", "c"]


def test_default_log_root_is_under_home(tmp_path, monkeypatch):
    """Without a log_root config override, the plugin uses ~/.athena/logs/shell_audit/."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    cls = _load_shell_audit_class()
    p = cls()
    p.name = "shell_audit"
    p.on_session_start("default-root", "default")
    p.post_tool_call("Bash", {"command": "ls"}, "ok")
    log_file = tmp_path / ".athena" / "logs" / "shell_audit" / "default-root.jsonl"
    assert log_file.exists()
