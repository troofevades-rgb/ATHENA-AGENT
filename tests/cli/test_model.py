"""ocode model CLI."""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

import ocode.cli.model as model_cli


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = model_cli.main(argv)
        except SystemExit as e:
            rc = int(e.code) if isinstance(e.code, int) else 2
    return rc, out.getvalue(), err.getvalue()


def test_model_list_shows_available_ollama_models(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(model_cli, "ensure_ollama", lambda: True)
    fake = [
        {"name": "qwen2.5-coder:14b", "id": "abc", "size": "8GB", "modified_at": "today"},
        {"name": "llama3.1:8b", "id": "def", "size": "4GB", "modified_at": "yesterday"},
    ]
    monkeypatch.setattr(model_cli, "list_local_models", lambda: fake)
    rc, stdout, _ = _run(["list"])
    assert rc == 0
    assert "qwen2.5-coder:14b" in stdout
    assert "llama3.1:8b" in stdout


def test_model_list_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(model_cli, "ensure_ollama", lambda: True)
    monkeypatch.setattr(model_cli, "list_local_models", lambda: [])
    rc, stdout, _ = _run(["list"])
    assert rc == 0
    assert "no local Ollama models" in stdout


def test_model_list_errors_without_ollama(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(model_cli, "ensure_ollama", lambda: False)
    rc, _, err = _run(["list"])
    assert rc == 2
    assert "ollama" in err


def test_model_switch_updates_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """ocode model switch <name> writes model = "<name>" to config.toml."""
    fake_config = tmp_path / "config.toml"
    monkeypatch.setattr(model_cli, "CONFIG_PATH", fake_config)
    monkeypatch.setattr(model_cli, "ensure_ollama", lambda: True)
    rc, stdout, _ = _run(["switch", "qwen-ocode-2"])
    assert rc == 0
    assert "qwen-ocode-2" in stdout
    data = tomllib.loads(fake_config.read_text(encoding="utf-8"))
    assert data["model"] == "qwen-ocode-2"


def test_model_switch_warns_when_ollama_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Without ollama on PATH, switch still updates config but warns."""
    fake_config = tmp_path / "config.toml"
    monkeypatch.setattr(model_cli, "CONFIG_PATH", fake_config)
    monkeypatch.setattr(model_cli, "ensure_ollama", lambda: False)
    rc, _, err = _run(["switch", "x"])
    assert rc == 0
    assert "ollama" in err.lower()
    assert tomllib.loads(fake_config.read_text(encoding="utf-8"))["model"] == "x"


def test_model_info_shows_metadata(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(model_cli, "ensure_ollama", lambda: True)
    monkeypatch.setattr(model_cli, "show_model", lambda name: f"# {name}\nFROM qwen")
    rc, stdout, _ = _run(["info", "qwen2.5-coder:14b"])
    assert rc == 0
    assert "qwen" in stdout.lower()


def test_model_info_errors_when_show_returns_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(model_cli, "ensure_ollama", lambda: True)
    monkeypatch.setattr(model_cli, "show_model", lambda name: "")
    rc, _, err = _run(["info", "nonexistent"])
    assert rc == 1
    assert "no output" in err
