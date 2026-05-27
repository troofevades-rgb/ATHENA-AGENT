"""Tests for the workspace_info tool — lets the model ask "where am I"
without burning a Bash turn."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_workspace_info_returns_json(tmp_path, monkeypatch):
    from athena.tools import file_ops

    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)
    out = file_ops.workspace_info()
    payload = json.loads(out)
    assert payload["workspace"] == str(tmp_path)


def test_workspace_info_includes_python_cwd(tmp_path, monkeypatch):
    from athena.tools import file_ops

    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)
    out = file_ops.workspace_info()
    payload = json.loads(out)
    assert "python_cwd" in payload
    # Should be a real path.
    assert Path(payload["python_cwd"]).exists() or payload["python_cwd"]


def test_workspace_info_match_flag(tmp_path, monkeypatch):
    """workspace_matches_cwd is True iff workspace == cwd."""
    from athena.tools import file_ops

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)
    payload = json.loads(file_ops.workspace_info())
    assert payload["workspace_matches_cwd"] is True


def test_workspace_info_match_false_when_diverged(tmp_path, monkeypatch):
    from athena.tools import file_ops

    diff_dir = tmp_path / "elsewhere"
    diff_dir.mkdir()
    monkeypatch.chdir(diff_dir)
    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)
    payload = json.loads(file_ops.workspace_info())
    assert payload["workspace_matches_cwd"] is False


def test_workspace_info_tool_registered():
    """The tool is in the registry and advertised under toolset=file."""
    import athena.tools  # noqa: F401 — populates registry
    from athena.tools.registry import get_tool

    t = get_tool("workspace_info")
    assert t is not None
    assert t.toolset == "file"
    # No required params — model can call with no args.
    assert t.parameters.get("required", []) == []


def test_workspace_info_includes_memory_dir(tmp_path, monkeypatch):
    """The memory_dir field tells the model where its memory lives —
    one of the most-asked questions across sessions."""
    from athena.tools import file_ops

    monkeypatch.setattr(file_ops, "_WORKSPACE", tmp_path)
    payload = json.loads(file_ops.workspace_info())
    assert "memory_dir" in payload
    # Either a real path or the (unavailable) sentinel — never a crash.
    assert payload["memory_dir"]
