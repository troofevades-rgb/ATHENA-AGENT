"""Ollama deploy: Modelfile writing, ollama-create invocation, switch_model."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

from ocode.transform.deploy import (
    list_local_models,
    register_with_ollama,
    show_model,
    switch_model,
)


def test_writes_modelfile(tmp_path: Path):
    gguf = tmp_path / "model.gguf"
    gguf.write_text("fake gguf data", encoding="utf-8")
    register_with_ollama(
        gguf, "test-model",
        base_system_prompt="be terse",
        runner=lambda cmd: 0,
    )
    modelfile = tmp_path / "Modelfile"
    body = modelfile.read_text(encoding="utf-8")
    assert f"FROM {gguf}" in body
    assert 'SYSTEM """be terse"""' in body


def test_writes_modelfile_without_system_prompt(tmp_path: Path):
    gguf = tmp_path / "model.gguf"
    gguf.write_text("data", encoding="utf-8")
    register_with_ollama(gguf, "no-system", runner=lambda cmd: 0)
    body = (tmp_path / "Modelfile").read_text(encoding="utf-8")
    assert "FROM" in body
    assert "SYSTEM" not in body


def test_calls_ollama_create(tmp_path: Path):
    gguf = tmp_path / "model.gguf"
    gguf.write_text("data", encoding="utf-8")
    captured: dict = {}

    def fake_call(cmd):
        captured["cmd"] = list(cmd)
        return 0

    rc = register_with_ollama(gguf, "qwen-ocode-1", runner=fake_call)
    assert rc == 0
    assert captured["cmd"][:3] == ["ollama", "create", "qwen-ocode-1"]
    assert "-f" in captured["cmd"]


def test_register_returns_exit_code(tmp_path: Path):
    gguf = tmp_path / "model.gguf"
    gguf.write_text("data", encoding="utf-8")
    assert register_with_ollama(gguf, "x", runner=lambda cmd: 11) == 11


# ---- switch_model -----------------------------------------------------


def test_switch_model_creates_config_when_missing(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    switch_model(cfg, "qwen2.5-coder:14b-ocode-1")
    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert data["model"] == "qwen2.5-coder:14b-ocode-1"


def test_switch_model_updates_existing_config(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'model = "old"\nollama_host = "http://127.0.0.1:11434"\n',
        encoding="utf-8",
    )
    switch_model(cfg, "new-model")
    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert data["model"] == "new-model"
    # Other keys preserved:
    assert data["ollama_host"] == "http://127.0.0.1:11434"


def test_switch_model_creates_parent_dirs(tmp_path: Path):
    cfg = tmp_path / "deep" / "nested" / "config.toml"
    switch_model(cfg, "x")
    assert cfg.exists()


# ---- list_local_models ------------------------------------------------


def test_list_local_models_parses_ollama_output():
    sample = (
        "NAME                    ID              SIZE    MODIFIED\n"
        "qwen2.5-coder:14b       abc123          8.0 GB  3 days ago\n"
        "llama3.1:8b             def456          4.5 GB  yesterday\n"
    )
    def fake_call(cmd):
        return 0, sample
    models = list_local_models(runner=fake_call)
    assert len(models) == 2
    assert models[0]["name"] == "qwen2.5-coder:14b"
    assert models[0]["id"] == "abc123"
    assert "3 days" in models[0]["modified_at"]
    assert models[1]["name"] == "llama3.1:8b"


def test_list_local_models_empty_output():
    def fake_call(cmd):
        return 0, "NAME  ID  SIZE  MODIFIED\n"
    assert list_local_models(runner=fake_call) == []


def test_list_local_models_nonzero_exit_returns_empty(caplog):
    import logging
    def fake_call(cmd):
        return 1, ""
    with caplog.at_level(logging.WARNING):
        assert list_local_models(runner=fake_call) == []


def test_list_local_models_missing_binary_returns_empty(caplog):
    import logging
    def fake_call(cmd):
        raise FileNotFoundError("ollama not on PATH")
    with caplog.at_level(logging.WARNING):
        assert list_local_models(runner=fake_call) == []
    assert any("ollama" in r.message for r in caplog.records)


def test_show_model_returns_stdout():
    def fake_call(cmd):
        return 0, "Modelfile: FROM qwen2.5-coder:14b\nSYSTEM ...\n"
    out = show_model("qwen2.5-coder:14b", runner=fake_call)
    assert "FROM" in out


def test_show_model_nonzero_returns_empty():
    def fake_call(cmd):
        return 1, ""
    assert show_model("x", runner=fake_call) == ""
