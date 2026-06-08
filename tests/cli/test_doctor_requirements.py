"""Tests for the requirement checks added to `athena doctor` — the
ones that would have caught the cross-machine setup failures (wrong
Python/venv, configured model not pulled, legacy console encoding)."""

from __future__ import annotations

import json
import sys
import types

from athena.cli import doctor


def test_python_runtime_check_shape() -> None:
    r = doctor._check_python_runtime()
    assert r.section == "python"
    assert r.severity in ("ok", "warn", "fail")
    assert "Python" in r.detail


def test_new_checks_are_registered() -> None:
    names = {r.name for r in doctor.run_all_checks(skip_network=True)}
    assert {"python.runtime", "ollama.model", "tui.encoding"}.issubset(names)


def _fake_tags(monkeypatch, model_names):
    """Make urllib.request.urlopen return an Ollama /api/tags payload."""
    payload = json.dumps({"models": [{"name": n} for n in model_names]}).encode()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return payload

    monkeypatch.setattr(doctor, "load_config", None, raising=False)
    import athena.config as _cfg

    monkeypatch.setattr(
        _cfg,
        "load_config",
        lambda: types.SimpleNamespace(model="qwen2.5-coder:7b", ollama_host="http://x"),
    )
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())


def test_configured_model_pulled_ok(monkeypatch) -> None:
    _fake_tags(monkeypatch, ["qwen2.5-coder:7b", "llama3.1:8b"])
    r = doctor._check_configured_model_pulled()
    assert r.severity == "ok"
    assert "present" in r.detail


def test_configured_model_pulled_warns_when_absent(monkeypatch) -> None:
    _fake_tags(monkeypatch, ["llama3.1:8b"])  # configured 7b is NOT here
    r = doctor._check_configured_model_pulled()
    assert r.severity == "warn"
    assert "ollama pull" in r.detail


def test_console_encoding_skips_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    r = doctor._check_console_encoding()
    assert r.severity == "skip"


def test_norm_model_adds_latest() -> None:
    assert doctor._norm_model("qwen2.5-coder") == "qwen2.5-coder:latest"
    assert doctor._norm_model("qwen2.5-coder:7b") == "qwen2.5-coder:7b"
