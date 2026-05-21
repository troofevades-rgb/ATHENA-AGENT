"""Version check + changelog preview tests (T6-07.2).

Network calls (urllib.request.urlopen) and subprocess
invocations (git ls-remote / git log) are stubbed so no real
PyPI or remote contact fires. Pure-function logic
(is_newer / _is_prerelease / _find_version_headings) gets
its own straight-shot tests.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

# Load the submodule via sys.modules — the __init__.py shadows
# the attribute (same workaround as test_detect.py).
import athena.update.check  # noqa: F401

check_module = sys.modules["athena.update.check"]
from athena.update.check import (
    _find_version_headings,
    _is_prerelease,
    _max_version,
    changelog_between,
    is_newer,
    latest_for,
    latest_git_tag,
    latest_pypi_version,
)
from athena.update.detect import InstallMethod


# ---------------------------------------------------------------------------
# is_newer / _parse
# ---------------------------------------------------------------------------


def test_is_newer_upgrade():
    assert is_newer("0.5.0", "0.6.0") is True
    assert is_newer("0.2.0", "0.2.1") is True
    assert is_newer("1.0.0", "2.0.0") is True


def test_is_newer_equal_or_downgrade_returns_false():
    assert is_newer("0.6.0", "0.6.0") is False
    assert is_newer("0.6.0", "0.5.9") is False
    assert is_newer("1.0.0", "0.999.999") is False


def test_is_newer_none_latest():
    """Offline case — latest is None → is_newer False so the
    command never advertises an unverified upgrade."""
    assert is_newer("0.5.0", None) is False
    assert is_newer("0.5.0", "") is False


def test_is_newer_handles_pep440_shapes():
    """Pre-release ordering: 1.0a1 < 1.0.0."""
    assert is_newer("1.0a1", "1.0.0") is True
    assert is_newer("1.0.0rc1", "1.0.0") is True


# ---------------------------------------------------------------------------
# Prerelease detection / channel filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "v",
    [
        "1.0.0a1",
        "1.0.0b2",
        "1.0.0rc1",
        "1.0.0.dev1",
        "1.0.0-alpha",
        "1.0.0-beta",
        "1.0.0-rc1",
    ],
)
def test_is_prerelease_true(v: str):
    assert _is_prerelease(v) is True


@pytest.mark.parametrize("v", ["1.0.0", "0.2.1", "2.0.0", "1.10.0"])
def test_is_prerelease_false(v: str):
    assert _is_prerelease(v) is False


def test_max_version_empty_returns_none():
    assert _max_version([]) is None


def test_max_version_picks_highest():
    assert _max_version(["0.1.0", "0.2.0", "0.1.9"]) == "0.2.0"
    assert _max_version(["1.0", "1.0.1"]) == "1.0.1"


# ---------------------------------------------------------------------------
# PyPI lookup
# ---------------------------------------------------------------------------


class _FakeURLOpenResponse:
    """File-like response from urlopen."""

    def __init__(self, payload: dict):
        self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self._buf

    def __exit__(self, *args):
        return False


def test_latest_pypi_returns_highest_stable(monkeypatch):
    payload = {
        "releases": {
            "0.1.0": [], "0.2.0": [], "0.3.0a1": [], "0.3.0b1": [],
            "0.3.0": [], "0.4.0": [],
        }
    }
    monkeypatch.setattr(
        check_module.urllib.request,
        "urlopen",
        lambda url, timeout=5: _FakeURLOpenResponse(payload),
    )
    assert latest_pypi_version("athena-coder", channel="stable") == "0.4.0"


def test_channel_pre_includes_prerelease(monkeypatch):
    """A pre-release version that's higher than the stable
    becomes the latest in the pre channel."""
    payload = {
        "releases": {
            "0.4.0": [], "0.5.0a1": [],
        }
    }
    monkeypatch.setattr(
        check_module.urllib.request,
        "urlopen",
        lambda url, timeout=5: _FakeURLOpenResponse(payload),
    )
    assert latest_pypi_version("x", channel="pre") == "0.5.0a1"
    assert latest_pypi_version("x", channel="stable") == "0.4.0"


def test_channel_stable_excludes_prerelease(monkeypatch):
    """The headline channel filter: stable releases exclude
    a1 / b1 / rc1 / dev shapes."""
    payload = {
        "releases": {
            "0.2.0": [], "0.3.0rc1": [], "0.3.0b1": [],
        }
    }
    monkeypatch.setattr(
        check_module.urllib.request,
        "urlopen",
        lambda url, timeout=5: _FakeURLOpenResponse(payload),
    )
    assert latest_pypi_version("x", channel="stable") == "0.2.0"


def test_latest_pypi_offline_returns_none(monkeypatch):
    """OSError from urlopen → None. No stack trace. The
    `athena update` command surfaces "offline" cleanly."""

    def _raise(*args, **kwargs):
        raise OSError("Network unreachable")

    monkeypatch.setattr(check_module.urllib.request, "urlopen", _raise)
    assert latest_pypi_version("x") is None


def test_latest_pypi_urlerror_returns_none(monkeypatch):
    """URLError (DNS failure / unreachable host) → None too."""

    def _raise(*args, **kwargs):
        raise urllib.error.URLError("DNS")

    monkeypatch.setattr(check_module.urllib.request, "urlopen", _raise)
    assert latest_pypi_version("x") is None


def test_latest_pypi_malformed_returns_none(monkeypatch):
    """JSON decode failure → None."""

    class _BadResponse:
        def __enter__(self):
            return io.BytesIO(b"not valid json {{{")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        check_module.urllib.request,
        "urlopen",
        lambda url, timeout=5: _BadResponse(),
    )
    assert latest_pypi_version("x") is None


def test_latest_pypi_missing_releases_key(monkeypatch):
    """Payload without a "releases" key (404-ish responses)
    → None."""
    monkeypatch.setattr(
        check_module.urllib.request,
        "urlopen",
        lambda url, timeout=5: _FakeURLOpenResponse({"info": "nothing here"}),
    )
    assert latest_pypi_version("x") is None


# ---------------------------------------------------------------------------
# latest_for dispatch
# ---------------------------------------------------------------------------


def test_latest_for_pip_uses_pypi(monkeypatch):
    monkeypatch.setattr(
        check_module,
        "latest_pypi_version",
        lambda pkg, channel="stable": "1.2.3",
    )
    monkeypatch.setattr(check_module, "latest_git_tag", lambda *a, **k: None)
    cfg = SimpleNamespace(update_channel="stable")
    assert latest_for(InstallMethod.PIP, cfg=cfg) == "1.2.3"


def test_latest_for_pipx_uses_pypi(monkeypatch):
    monkeypatch.setattr(
        check_module,
        "latest_pypi_version",
        lambda pkg, channel="stable": "1.2.3",
    )
    assert latest_for(InstallMethod.PIPX) == "1.2.3"


def test_latest_for_git_uses_ls_remote(monkeypatch):
    monkeypatch.setattr(check_module, "latest_git_tag", lambda *a, **k: "0.9.0")
    assert latest_for(InstallMethod.GIT) == "0.9.0"


def test_latest_for_editable_returns_none():
    """EDITABLE → None because the command warns + exits."""
    assert latest_for(InstallMethod.EDITABLE) is None


def test_latest_for_unknown_returns_none():
    assert latest_for(InstallMethod.UNKNOWN) is None


def test_latest_for_channel_propagates(monkeypatch):
    """cfg.update_channel reaches latest_pypi_version."""
    seen: dict = {}

    def _stub(pkg, channel="stable"):
        seen["channel"] = channel
        return "1.0.0"

    monkeypatch.setattr(check_module, "latest_pypi_version", _stub)
    cfg = SimpleNamespace(update_channel="pre")
    latest_for(InstallMethod.PIP, cfg=cfg)
    assert seen["channel"] == "pre"


# ---------------------------------------------------------------------------
# git ls-remote
# ---------------------------------------------------------------------------


def test_latest_git_tag_returns_highest(monkeypatch):
    """Standard `git ls-remote --tags origin` output parsed +
    the highest version wins."""
    stdout = "\n".join(
        [
            "abc123\trefs/tags/v0.1.0",
            "def456\trefs/tags/v0.2.0",
            "ghi789\trefs/tags/v0.2.0^{}",  # peeled tag
            "jkl012\trefs/tags/v0.3.0",
        ]
    )
    monkeypatch.setattr(
        check_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )
    assert latest_git_tag() == "0.3.0"


def test_latest_git_tag_handles_no_v_prefix(monkeypatch):
    stdout = "abc\trefs/tags/0.1.0\ndef\trefs/tags/0.2.0\n"
    monkeypatch.setattr(
        check_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )
    assert latest_git_tag() == "0.2.0"


def test_latest_git_tag_no_git_returns_none(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("git not on PATH")

    monkeypatch.setattr(check_module.subprocess, "run", _raise)
    assert latest_git_tag() is None


def test_latest_git_tag_nonzero_exit_returns_none(monkeypatch):
    monkeypatch.setattr(
        check_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="no remote"),
    )
    assert latest_git_tag() is None


# ---------------------------------------------------------------------------
# Changelog heading parsing
# ---------------------------------------------------------------------------


def test_find_version_headings_bracketed():
    text = """
# Changelog

## [Unreleased]
### Added
- thing

## [0.3.0] - 2026-01-01
### Added
- another

## [0.2.0] - 2025-12-01
### Added
- earlier
"""
    headings = _find_version_headings(text)
    versions = [v for _, v in headings]
    assert "unreleased" in versions
    assert "0.3.0" in versions
    assert "0.2.0" in versions


def test_find_version_headings_bare():
    text = """
## 0.3.0
## v0.2.0
## 0.1.0
"""
    versions = [v for _, v in _find_version_headings(text)]
    # The v-prefix is stripped at capture time — the capture
    # group matches just the digits.
    assert versions == ["0.3.0", "0.2.0", "0.1.0"]


# ---------------------------------------------------------------------------
# changelog_between
# ---------------------------------------------------------------------------


def test_changelog_between_returns_sections(monkeypatch, tmp_path: Path):
    """Slice from latest's heading down to current's heading."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "\n".join(
            [
                "# Changelog",
                "",
                "## [0.4.0] - 2026-02-01",
                "### Added",
                "- newest stuff",
                "",
                "## [0.3.0] - 2026-01-01",
                "### Added",
                "- middle stuff",
                "",
                "## [0.2.0] - 2025-12-01",
                "### Added",
                "- old stuff",
            ]
        ),
        encoding="utf-8",
    )
    out = changelog_between(
        "0.2.0", "0.4.0",
        method=InstallMethod.PIP,
        changelog_path=str(changelog),
    )
    assert "0.4.0" in out
    assert "newest stuff" in out
    assert "0.3.0" in out
    assert "middle stuff" in out
    # Current's section is the EXCLUSIVE end — its own content
    # is not in the slice.
    assert "old stuff" not in out


def test_changelog_between_missing_file(monkeypatch, tmp_path: Path):
    """No CHANGELOG anywhere → pointer fallback string."""
    out = changelog_between(
        "0.1.0", "0.2.0",
        method=InstallMethod.PIP,
        changelog_path=str(tmp_path / "missing.md"),
    )
    assert "Changelog details unavailable" in out


def test_changelog_between_git_uses_git_log(monkeypatch):
    """Method=GIT runs `git log v0.2.0..v0.3.0 --oneline`."""
    monkeypatch.setattr(
        check_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout="abc123 feat: new thing\ndef456 fix: bug",
            stderr="",
        ),
    )
    out = changelog_between("0.2.0", "0.3.0", method=InstallMethod.GIT)
    assert "feat: new thing" in out
    assert "fix: bug" in out


def test_changelog_between_git_fallback_when_git_missing(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("git not on PATH")

    monkeypatch.setattr(check_module.subprocess, "run", _raise)
    out = changelog_between("0.2.0", "0.3.0", method=InstallMethod.GIT)
    assert "Changelog details unavailable" in out
