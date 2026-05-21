"""`athena update` command tests (T6-07.4).

Exercises the CLI entry's three branches (--check / install /
--rollback) plus the auto-check startup notice. Stubs the
detect / check / apply layers so no real network / pip /
git fires.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.commands import update as update_cmd
from athena.update.apply import ApplyResult
from athena.update.detect import InstallMethod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(tmp_path: Path, **overrides) -> SimpleNamespace:
    base = dict(
        update_source="auto",
        update_channel="stable",
        update_auto_check=False,
        update_state_path=str(tmp_path / "state.json"),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_cfg(monkeypatch, cfg: SimpleNamespace) -> None:
    monkeypatch.setattr("athena.config.load_config", lambda: cfg)


def _patch_detect(monkeypatch, method: InstallMethod) -> None:
    """Patch detect via sys.modules to dodge the __init__.py
    attribute shadowing."""
    import athena.update.detect  # noqa: F401

    monkeypatch.setattr(
        sys.modules["athena.update.detect"], "detect", lambda pkg="athena-coder": method
    )


def _patch_latest(monkeypatch, version: str | None) -> None:
    import athena.update.check  # noqa: F401

    monkeypatch.setattr(
        sys.modules["athena.update.check"],
        "latest_for",
        lambda method, *, cfg=None, pkg="athena-coder": version,
    )


def _patch_changelog(monkeypatch, text: str = "(no changelog)") -> None:
    import athena.update.check  # noqa: F401

    monkeypatch.setattr(
        sys.modules["athena.update.check"],
        "changelog_between",
        lambda current, latest, **kw: text,
    )


def _patch_current_version(monkeypatch, version: str) -> None:
    monkeypatch.setattr(update_cmd, "_resolve_current_version", lambda: version)


def _patch_install(monkeypatch, result: ApplyResult) -> list:
    import athena.update.apply  # noqa: F401

    calls: list[dict] = []

    def _stub(method, *, version=None, repo_root=None, pkg="athena-coder", cfg=None):
        calls.append(
            {
                "method": method,
                "version": version,
                "cfg": cfg,
            }
        )
        return result

    monkeypatch.setattr(sys.modules["athena.update.apply"], "install", _stub)
    return calls


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------


def test_check_only_installs_nothing(monkeypatch, tmp_path: Path):
    """`--check` reports current vs latest + changelog but
    NEVER calls install. The load-bearing dry-run pin."""
    _patch_cfg(monkeypatch, _cfg(tmp_path))
    _patch_detect(monkeypatch, InstallMethod.PIP)
    _patch_current_version(monkeypatch, "0.2.0")
    _patch_latest(monkeypatch, "0.3.0")
    _patch_changelog(monkeypatch, "## [0.3.0]\nthings")
    install_calls = _patch_install(
        monkeypatch, ApplyResult(status="done", method="pip")
    )

    rc = update_cmd.main(["--check"])
    assert rc == 0
    # CRITICAL: install was not called.
    assert install_calls == []


def test_check_up_to_date(monkeypatch, tmp_path: Path, capsys):
    """`--check` against an up-to-date install reports it
    cleanly + exits 0."""
    _patch_cfg(monkeypatch, _cfg(tmp_path))
    _patch_detect(monkeypatch, InstallMethod.PIP)
    _patch_current_version(monkeypatch, "0.3.0")
    _patch_latest(monkeypatch, "0.3.0")

    rc = update_cmd.main(["--check"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "up to date" in out


def test_check_offline_returns_cleanly(monkeypatch, tmp_path: Path, capsys):
    """latest_for=None (offline) → warn + exit 0, no install
    call. The "offline never crashes" invariant."""
    _patch_cfg(monkeypatch, _cfg(tmp_path))
    _patch_detect(monkeypatch, InstallMethod.PIP)
    _patch_current_version(monkeypatch, "0.2.0")
    _patch_latest(monkeypatch, None)
    install_calls = _patch_install(
        monkeypatch, ApplyResult(status="done", method="pip")
    )

    rc = update_cmd.main(["--check"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "offline" in out.lower() or "could not reach" in out.lower()
    assert install_calls == []


# ---------------------------------------------------------------------------
# Default install flow
# ---------------------------------------------------------------------------


def test_offline_makes_no_changes(monkeypatch, tmp_path: Path, capsys):
    """The headline offline-safe pin: no network → warn,
    install NOT called."""
    _patch_cfg(monkeypatch, _cfg(tmp_path))
    _patch_detect(monkeypatch, InstallMethod.PIP)
    _patch_current_version(monkeypatch, "0.2.0")
    _patch_latest(monkeypatch, None)
    install_calls = _patch_install(
        monkeypatch, ApplyResult(status="done", method="pip")
    )

    rc = update_cmd.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "offline" in out.lower() or "could not reach" in out.lower()
    assert install_calls == []


def test_up_to_date_no_action(monkeypatch, tmp_path: Path, capsys):
    """Latest = current → no install call."""
    _patch_cfg(monkeypatch, _cfg(tmp_path))
    _patch_detect(monkeypatch, InstallMethod.PIP)
    _patch_current_version(monkeypatch, "0.3.0")
    _patch_latest(monkeypatch, "0.3.0")
    install_calls = _patch_install(
        monkeypatch, ApplyResult(status="done", method="pip")
    )

    rc = update_cmd.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "up to date" in out
    assert install_calls == []


def test_install_flow_with_yes(monkeypatch, tmp_path: Path):
    """--yes bypasses the confirm prompt; record_prior + install
    fire; success exit 0."""
    _patch_cfg(monkeypatch, _cfg(tmp_path))
    _patch_detect(monkeypatch, InstallMethod.PIP)
    _patch_current_version(monkeypatch, "0.2.0")
    _patch_latest(monkeypatch, "0.3.0")
    _patch_changelog(monkeypatch)
    install_calls = _patch_install(
        monkeypatch,
        ApplyResult(
            status="done",
            method="pip",
            version_installed="0.3.0",
            message="installed athena-coder 0.3.0 via pip — restart athena to use it",
        ),
    )

    rc = update_cmd.main(["--yes"])
    assert rc == 0
    assert len(install_calls) == 1
    assert install_calls[0]["version"] == "0.3.0"


def test_install_records_prior_version(monkeypatch, tmp_path: Path):
    """Before install, record_prior writes the current version
    to update_state.json (the rollback target)."""
    cfg = _cfg(tmp_path)
    _patch_cfg(monkeypatch, cfg)
    _patch_detect(monkeypatch, InstallMethod.PIP)
    _patch_current_version(monkeypatch, "0.2.0")
    _patch_latest(monkeypatch, "0.3.0")
    _patch_changelog(monkeypatch)
    _patch_install(
        monkeypatch, ApplyResult(status="done", method="pip", version_installed="0.3.0")
    )

    update_cmd.main(["--yes"])

    # State file written.
    state_file = Path(cfg.update_state_path)
    assert state_file.exists()
    import json

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["prior_version"] == "0.2.0"


def test_install_pinned_skips_latest_lookup(monkeypatch, tmp_path: Path):
    """--to <version> goes straight to install with that
    version — no latest_for call needed."""
    _patch_cfg(monkeypatch, _cfg(tmp_path))
    _patch_detect(monkeypatch, InstallMethod.PIP)
    _patch_current_version(monkeypatch, "0.3.0")

    # If --to was honoured, latest_for shouldn't be consulted.
    latest_calls = {"n": 0}

    def _spy_latest(*a, **k):
        latest_calls["n"] += 1
        return "0.5.0"

    import athena.update.check  # noqa: F401

    monkeypatch.setattr(
        sys.modules["athena.update.check"], "latest_for", _spy_latest
    )

    install_calls = _patch_install(
        monkeypatch, ApplyResult(status="done", method="pip", version_installed="0.4.2")
    )
    rc = update_cmd.main(["--to", "0.4.2", "--yes"])
    assert rc == 0
    assert latest_calls["n"] == 0
    assert install_calls[0]["version"] == "0.4.2"


def test_editable_refused(monkeypatch, tmp_path: Path, capsys):
    """EDITABLE → warn + exit 1, install NOT called."""
    _patch_cfg(monkeypatch, _cfg(tmp_path))
    _patch_detect(monkeypatch, InstallMethod.EDITABLE)
    _patch_current_version(monkeypatch, "0.2.0")
    install_calls = _patch_install(
        monkeypatch, ApplyResult(status="done", method="pip")
    )

    rc = update_cmd.main(["--yes"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "editable" in out.lower()
    assert install_calls == []


def test_unknown_refused(monkeypatch, tmp_path: Path):
    """UNKNOWN → warn + exit 1."""
    _patch_cfg(monkeypatch, _cfg(tmp_path))
    _patch_detect(monkeypatch, InstallMethod.UNKNOWN)
    _patch_current_version(monkeypatch, "0.2.0")
    install_calls = _patch_install(
        monkeypatch, ApplyResult(status="done", method="pip")
    )

    rc = update_cmd.main([])
    assert rc == 1
    assert install_calls == []


# ---------------------------------------------------------------------------
# --rollback
# ---------------------------------------------------------------------------


def test_rollback_with_no_prior_recorded(monkeypatch, tmp_path: Path, capsys):
    """--rollback with no prior recorded → warn + exit 1."""
    _patch_cfg(monkeypatch, _cfg(tmp_path))

    rc = update_cmd.main(["--rollback", "--yes"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "no prior" in out.lower()


def test_rollback_installs_prior_version(monkeypatch, tmp_path: Path):
    """rollback() returns success → command exit 0."""
    cfg = _cfg(tmp_path)
    _patch_cfg(monkeypatch, cfg)
    # Plant a prior version.
    from athena.update.apply import record_prior

    record_prior("0.1.5", cfg=cfg)

    import athena.update.apply  # noqa: F401

    def _stub_rollback(*, cfg=None, pkg="athena-coder"):
        return ApplyResult(
            status="done",
            method="pip",
            version_installed="0.1.5",
            message="rolled back to 0.1.5",
        )

    monkeypatch.setattr(
        sys.modules["athena.update.apply"], "rollback", _stub_rollback
    )

    rc = update_cmd.main(["--rollback", "--yes"])
    assert rc == 0


# ---------------------------------------------------------------------------
# Mutually exclusive flags
# ---------------------------------------------------------------------------


def test_check_and_rollback_mutually_exclusive(monkeypatch, tmp_path: Path):
    _patch_cfg(monkeypatch, _cfg(tmp_path))
    with pytest.raises(SystemExit):
        update_cmd.main(["--check", "--rollback"])


def test_check_and_to_mutually_exclusive(monkeypatch, tmp_path: Path):
    _patch_cfg(monkeypatch, _cfg(tmp_path))
    with pytest.raises(SystemExit):
        update_cmd.main(["--check", "--to", "0.3.0"])


def test_rollback_and_to_mutually_exclusive(monkeypatch, tmp_path: Path):
    _patch_cfg(monkeypatch, _cfg(tmp_path))
    with pytest.raises(SystemExit):
        update_cmd.main(["--rollback", "--to", "0.3.0"])


# ---------------------------------------------------------------------------
# startup_notice (auto-check)
# ---------------------------------------------------------------------------


def test_auto_check_off_by_default(monkeypatch, tmp_path: Path, capsys):
    """update_auto_check=False (the default) → startup_notice
    is a complete no-op. No version lookup, no output."""
    lookup_calls = {"n": 0}

    def _spy_latest(*a, **k):
        lookup_calls["n"] += 1
        return "1.0.0"

    import athena.update.check  # noqa: F401

    monkeypatch.setattr(
        sys.modules["athena.update.check"],
        "latest_pypi_version",
        _spy_latest,
    )

    cfg = _cfg(tmp_path, update_auto_check=False)
    update_cmd.startup_notice(cfg)
    out = capsys.readouterr().out
    assert lookup_calls["n"] == 0  # no PyPI call attempted
    assert out == "" or "athena" not in out.lower()


def test_auto_check_prints_notice_when_newer(monkeypatch, tmp_path: Path, capsys):
    """update_auto_check=True + a newer version → one-line
    "available" notice, NEVER auto-installs."""
    _patch_detect(monkeypatch, InstallMethod.PIP)
    _patch_current_version(monkeypatch, "0.2.0")

    import athena.update.check  # noqa: F401

    monkeypatch.setattr(
        sys.modules["athena.update.check"],
        "latest_pypi_version",
        lambda channel="stable", timeout=3.0: "0.3.0",
    )

    install_calls = _patch_install(
        monkeypatch, ApplyResult(status="done", method="pip")
    )

    cfg = _cfg(tmp_path, update_auto_check=True)
    update_cmd.startup_notice(cfg)
    out = capsys.readouterr().out
    assert "0.3.0" in out
    assert "available" in out.lower()
    # Critical: NEVER auto-installs.
    assert install_calls == []


def test_auto_check_skips_editable(monkeypatch, tmp_path: Path, capsys):
    """EDITABLE / UNKNOWN installs don't get an auto-check
    notice — the upgrade path isn't relevant to them."""
    _patch_detect(monkeypatch, InstallMethod.EDITABLE)

    lookup_calls = {"n": 0}

    def _spy_latest(*a, **k):
        lookup_calls["n"] += 1
        return "0.3.0"

    import athena.update.check  # noqa: F401

    monkeypatch.setattr(
        sys.modules["athena.update.check"],
        "latest_pypi_version",
        _spy_latest,
    )

    cfg = _cfg(tmp_path, update_auto_check=True)
    update_cmd.startup_notice(cfg)
    assert lookup_calls["n"] == 0  # never even checked


def test_auto_check_silent_on_offline(monkeypatch, tmp_path: Path, capsys):
    """auto-check + offline (latest=None) → no notice, no
    crash. The "courtesy, not a feature gate" invariant."""
    _patch_detect(monkeypatch, InstallMethod.PIP)
    _patch_current_version(monkeypatch, "0.2.0")

    import athena.update.check  # noqa: F401

    monkeypatch.setattr(
        sys.modules["athena.update.check"],
        "latest_pypi_version",
        lambda channel="stable", timeout=3.0: None,
    )

    cfg = _cfg(tmp_path, update_auto_check=True)
    update_cmd.startup_notice(cfg)
    out = capsys.readouterr().out
    # Silent — no notice when offline.
    assert "available" not in out.lower()


def test_auto_check_silent_on_exception(monkeypatch, tmp_path: Path, capsys):
    """Any exception in the lookup → silent no-op. The notice
    is a courtesy; it must NEVER break startup."""

    def _explode(*a, **k):
        raise RuntimeError("PyPI exploded")

    import athena.update.check  # noqa: F401

    monkeypatch.setattr(
        sys.modules["athena.update.check"],
        "latest_pypi_version",
        _explode,
    )

    cfg = _cfg(tmp_path, update_auto_check=True)
    # Should NOT raise.
    update_cmd.startup_notice(cfg)
    out = capsys.readouterr().out
    # No noisy error message.
    assert "PyPI exploded" not in out
