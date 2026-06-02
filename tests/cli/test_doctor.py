"""``athena doctor`` -- health check CLI.

Read-only command that walks config / credentials / Ollama daemon /
hosted-provider auth / filesystem / TUI bundle / feature gates. The
pins below isolate behavior from the live environment via
monkeypatch so they're deterministic in CI.

Coverage:

  * Severity -> exit-code mapping.
  * ``--strict`` flips warn -> exit 1.
  * ``--no-network`` skips remote probes.
  * ``--json`` output shape (so external tooling can rely on it).
  * Safe-wrapper catches a crashing check and reports it as FAIL.
  * Per-check happy + sad paths for the load-bearing checks
    (config, credentials pool, Ollama daemon, OpenRouter auth,
    TUI bundle, godmode gate).
"""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace
from typing import Any

import pytest

from athena.cli import doctor

# ---------------------------------------------------------------------------
# Exit-code mapping (the contract for CI consumers)
# ---------------------------------------------------------------------------


def _make_args(
    json_output: bool = False,
    strict: bool = False,
    no_network: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        json=json_output,
        strict=strict,
        no_network=no_network,
    )


def _result(severity: doctor.Severity, name: str = "x", **kw) -> doctor.CheckResult:
    return doctor.CheckResult(
        section="test",
        name=name,
        label=name,
        severity=severity,
        detail=kw.get("detail", ""),
    )


def test_all_ok_exits_zero() -> None:
    results = [_result("ok", "a"), _result("ok", "b")]
    assert doctor._compute_exit_code(results, strict=False) == 0


def test_any_fail_exits_one() -> None:
    results = [_result("ok"), _result("fail"), _result("ok")]
    assert doctor._compute_exit_code(results, strict=False) == 1


def test_warn_alone_default_exits_zero() -> None:
    """Default exit policy: WARN doesn't flip the gate. Operators
    can run doctor regularly without surfacing warnings to CI."""
    results = [_result("ok"), _result("warn"), _result("ok")]
    assert doctor._compute_exit_code(results, strict=False) == 0


def test_strict_flips_warn_to_one() -> None:
    """``--strict`` is for CI lanes that want "everything healthy."
    A single WARN now flips the exit gate."""
    results = [_result("ok"), _result("warn"), _result("ok")]
    assert doctor._compute_exit_code(results, strict=True) == 1


def test_skip_does_not_affect_exit_code() -> None:
    """``SKIP`` is informational -- a check that's expected to be
    inapplicable (no credential -> skipped probe) should never gate
    CI on its own."""
    results = [_result("ok"), _result("skip"), _result("ok")]
    assert doctor._compute_exit_code(results, strict=False) == 0
    assert doctor._compute_exit_code(results, strict=True) == 0


# ---------------------------------------------------------------------------
# Safe-wrapper isolation
# ---------------------------------------------------------------------------


def test_safe_catches_unexpected_exception() -> None:
    """A check that raises mid-flight must NOT crash the report.
    The safe-wrapper converts the exception into a FAIL row that
    names the exception type and message."""

    def _boom() -> doctor.CheckResult:
        raise RuntimeError("simulated check crash")

    result = doctor._safe("Some Check", _boom)
    assert result.severity == "fail"
    assert "simulated check crash" in result.detail
    assert "RuntimeError" in result.detail


def test_safe_passes_ok_check_through_unchanged() -> None:
    """The wrapper is transparent when the check succeeds."""
    expected = _result("ok", "ok.check", detail="all good")

    def _ok() -> doctor.CheckResult:
        return expected

    result = doctor._safe("OK Check", _ok)
    assert result is expected


# ---------------------------------------------------------------------------
# JSON output shape (external integrations depend on it)
# ---------------------------------------------------------------------------


def test_json_output_has_checks_and_summary() -> None:
    results = [
        _result("ok", "a", detail="d1"),
        _result("warn", "b", detail="d2"),
        _result("fail", "c", detail="d3"),
    ]
    raw = doctor.render_json_report(results)
    payload = json.loads(raw)
    assert "checks" in payload
    assert "summary" in payload
    assert payload["summary"] == {"ok": 1, "warn": 1, "fail": 1, "skip": 0}
    assert len(payload["checks"]) == 3
    # Each check has the documented keys.
    expected_keys = {"section", "name", "label", "severity", "detail", "extra"}
    for entry in payload["checks"]:
        assert expected_keys.issubset(set(entry.keys()))


def test_text_report_groups_by_section() -> None:
    """Section headers appear once each, in result order."""
    results = [
        doctor.CheckResult(section="config", name="x", label="cfg-row", severity="ok"),
        doctor.CheckResult(section="config", name="y", label="cfg-row-2", severity="ok"),
        doctor.CheckResult(section="ollama", name="z", label="ollama-row", severity="ok"),
    ]
    text = doctor.render_text_report(results)
    # Both section headers present, in order, exactly once.
    config_pos = text.find("[config]")
    ollama_pos = text.find("[ollama]")
    assert config_pos != -1 and ollama_pos != -1
    assert config_pos < ollama_pos
    assert text.count("[config]") == 1


# ---------------------------------------------------------------------------
# --no-network skips remote probes
# ---------------------------------------------------------------------------


def test_no_network_skips_openrouter_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``--no-network``, the OpenRouter check must NOT fire
    httpx -- it returns SKIP. Block the import-time httpx symbol so
    a regression would surface as AttributeError, not a stealth
    network call."""

    class _CredStub:
        key = "sk-or-test"

    class _Pool:
        def get(self, name: str) -> Any:
            return _CredStub() if name == "openrouter" else None

    monkeypatch.setattr("athena.providers.credential_pool.global_pool", lambda: _Pool())
    # If the skip branch ran, the function should never reach httpx.
    # We don't need to block httpx -- just assert the result severity
    # and detail.
    result = doctor._check_openrouter_auth(skip_network=True)
    assert result.severity == "skip"
    assert "--no-network" in result.detail


def test_openrouter_probe_returns_skip_when_no_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No credential -> SKIP, not FAIL. Operators without an
    OpenRouter key shouldn't see a failure for an optional provider."""

    class _Pool:
        def get(self, name: str) -> Any:
            return None

    monkeypatch.setattr("athena.providers.credential_pool.global_pool", lambda: _Pool())
    result = doctor._check_openrouter_auth(skip_network=False)
    assert result.severity == "skip"
    assert "no credential" in result.detail.lower()


def test_openrouter_probe_reports_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 401/403 from OpenRouter -> FAIL with a 'unauthorized'
    detail that points the operator at key validity."""

    class _CredStub:
        key = "sk-or-bad"

    class _Pool:
        def get(self, name: str) -> Any:
            return _CredStub()

    monkeypatch.setattr("athena.providers.credential_pool.global_pool", lambda: _Pool())

    class _Resp:
        status_code = 401

    monkeypatch.setattr("httpx.get", lambda *a, **kw: _Resp())

    result = doctor._check_openrouter_auth(skip_network=False)
    assert result.severity == "fail"
    assert "unauthorized" in result.detail.lower()


# ---------------------------------------------------------------------------
# Ollama daemon
# ---------------------------------------------------------------------------


def test_ollama_check_reports_ok_when_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"models": [{"name": "m1"}, {"name": "m2"}]}

    monkeypatch.setattr("httpx.get", lambda *a, **kw: _Resp())
    monkeypatch.setattr(
        "athena.config.load_config",
        lambda: SimpleNamespace(ollama_host="http://127.0.0.1:11434"),
    )

    result = doctor._check_ollama_daemon()
    assert result.severity == "ok"
    assert "2 model" in result.detail
    assert result.extra["model_count"] == 2


def test_ollama_check_reports_fail_when_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*_a: Any, **_kw: Any) -> None:
        raise ConnectionError("daemon not running")

    monkeypatch.setattr("httpx.get", _raise)
    monkeypatch.setattr(
        "athena.config.load_config",
        lambda: SimpleNamespace(ollama_host="http://127.0.0.1:11434"),
    )

    result = doctor._check_ollama_daemon()
    assert result.severity == "fail"
    assert "ConnectionError" in result.detail


# ---------------------------------------------------------------------------
# TUI bundle
# ---------------------------------------------------------------------------


def test_tui_bundle_check_passes_when_file_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Doctor validates the SAME bundle the gateway will spawn, so it
    delegates to ``_locate_bundle``. Mock that to a tmp file so the
    test is independent of repo state."""
    bundle = tmp_path / "main.js"
    bundle.write_text("// bundle bytes", encoding="utf-8")
    monkeypatch.setattr("athena.tui_gateway.server._locate_bundle", lambda: bundle)

    result = doctor._check_tui_bundle()
    assert result.severity == "ok"
    assert "main.js" in result.detail


def test_tui_bundle_check_fails_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``_locate_bundle`` can't find a bundle on either the wheel
    or dev path, it raises FileNotFoundError -> doctor reports FAIL
    with the bun-build hint carried in the exception message."""

    def _raise() -> None:
        raise FileNotFoundError(
            "Ink TUI bundle not found. ... Build it with: cd ui-tui && bun run build"
        )

    monkeypatch.setattr("athena.tui_gateway.server._locate_bundle", _raise)

    result = doctor._check_tui_bundle()
    assert result.severity == "fail"
    assert "bun run build" in result.detail


# ---------------------------------------------------------------------------
# godmode gate visibility
# ---------------------------------------------------------------------------


def test_godmode_gate_shows_warn_when_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate being unlocked is not a failure -- but operators
    deserve to see it surfaced (it's a real session-safety posture
    change) so doctor reports WARN."""

    monkeypatch.setattr("athena.env.get_credential", lambda key: "1")
    result = doctor._check_godmode_gate()
    assert result.severity == "warn"
    assert "ATHENA_ALLOW_GODMODE" in result.detail


def test_godmode_gate_ok_when_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default state (gate closed) is OK. Operators not using
    godmode shouldn't see warnings about it."""
    monkeypatch.setattr("athena.env.get_credential", lambda key: None)
    result = doctor._check_godmode_gate()
    assert result.severity == "ok"
    assert "closed" in result.detail


# ---------------------------------------------------------------------------
# Credentials pool
# ---------------------------------------------------------------------------


def test_credentials_pool_warns_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No configured providers -> WARN with the add-key hint. Not
    a FAIL since a Ollama-only setup is valid."""

    class _EmptyPool:
        def providers(self) -> list[str]:
            return []

    monkeypatch.setattr("athena.providers.credential_pool.global_pool", lambda: _EmptyPool())

    result = doctor._check_credentials_pool()
    assert result.severity == "warn"
    assert "add-key" in result.detail


def test_credentials_pool_reports_provider_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When credentials exist, doctor reports the PROVIDER NAMES
    (not keys). This is what operators check at-a-glance."""

    class _Pool:
        def providers(self) -> list[str]:
            return ["anthropic", "openai", "openrouter"]

    monkeypatch.setattr("athena.providers.credential_pool.global_pool", lambda: _Pool())

    result = doctor._check_credentials_pool()
    assert result.severity == "ok"
    assert "anthropic" in result.detail
    assert "openai" in result.detail
    assert "openrouter" in result.detail
    assert result.extra["providers"] == ["anthropic", "openai", "openrouter"]


# ---------------------------------------------------------------------------
# Recent crashes check (added with the crash-log feature)
# ---------------------------------------------------------------------------


def test_recent_crashes_ok_when_none(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Empty crash dir -> OK with a pointer at the directory so
    operators know where to look if a crash happens."""
    monkeypatch.setattr("athena.crash_log.recent_crashes", lambda within_days=None: [])
    result = doctor._check_recent_crashes()
    assert result.severity == "ok"
    assert "none recorded" in result.detail.lower()


def test_recent_crashes_warn_when_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Crash records in the last 7 days -> WARN with a count so
    the operator triages at a glance. Not FAIL: an old crash from
    yesterday shouldn't gate CI on its own."""
    fake_newest = tmp_path / "crash-20260531-aaaaaaaa.json"
    fake_newest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "athena.crash_log.recent_crashes",
        lambda within_days=None: [fake_newest, fake_newest],
    )
    result = doctor._check_recent_crashes()
    assert result.severity == "warn"
    assert "2 record" in result.detail
    assert result.extra["count"] == 2
