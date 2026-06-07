"""Latest-version lookup + changelog preview (T6-07.2).

Two surfaces:

  ``latest_for(method, *, cfg)``       → version string | None
    PyPI JSON for pip/pipx; ``git ls-remote`` for source
    installs. Returns None on OSError / unreachable — the
    "offline" case the command surfaces cleanly.

  ``changelog_between(current, latest, *, method)`` → str
    Best-effort preview. For PyPI: extract section headings
    between the two versions from the packaged CHANGELOG.md
    if it ships with the install. For git: ``git log
    --oneline`` between tags.

Auxiliaries:

  ``is_newer(current, latest)``        proper version comparison
  ``latest_pypi_version(pkg, *, channel)``   the PyPI lookup

The version comparison uses :mod:`packaging.version` when
available (it's pip's dependency so it's almost always
present), falling back to a tuple-of-ints split for the
common ``a.b.c`` shape so this module doesn't hard-depend on
``packaging``.

Pure I/O at the network boundary; everything else is string
manipulation. ``urlopen`` is the only network call and tests
monkeypatch it to a stub.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from .detect import PACKAGE_NAME, InstallMethod

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


_PYPI_TIMEOUT = 5.0
_PYPI_URL_TEMPLATE = "https://pypi.org/pypi/{pkg}/json"

# A version is "pre-release" if it contains an alpha / beta /
# release-candidate / dev tag. PEP 440 covers more shapes but
# this matches the practical set without dragging in the
# `packaging` library at import time.
_PRERELEASE_RX = re.compile(r"(?i)(?:[._-]?(?:a|alpha|b|beta|rc|c|dev|pre)\d*)\b")


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------


def _parse(version: str) -> Any:
    """Convert a version string to something orderable.

    Prefers :mod:`packaging.version.Version` (handles every
    PEP 440 shape correctly). Falls back to a tuple-of-ints
    split on dots — adequate for the common ``a.b.c`` form
    athena uses for releases. ``"abc"`` (non-numeric) sorts
    LAST in the fallback so a corrupted PyPI entry doesn't
    surface as "latest"."""
    try:
        from packaging.version import Version

        return Version(version)
    except Exception:  # noqa: BLE001
        pass
    parts: list[Any] = []
    for chunk in version.split("."):
        try:
            parts.append((0, int(chunk)))
        except ValueError:
            # Non-numeric chunk → push to a "lower" bucket so
            # numeric versions win comparisons against garbage.
            parts.append((-1, chunk))
    return tuple(parts)


def is_newer(current: str, latest: str | None) -> bool:
    """``True`` iff ``latest`` is strictly newer than
    ``current``. ``latest=None`` (offline / lookup failed) →
    False so the command never advertises an update it
    couldn't verify."""
    if not latest:
        return False
    try:
        return bool(_parse(latest) > _parse(current))
    except Exception:  # noqa: BLE001
        return False


def _is_prerelease(version: str) -> bool:
    """Return True for alpha/beta/rc/dev releases. Used by
    the channel filter."""
    return bool(_PRERELEASE_RX.search(version))


def _max_version(versions: list[str]) -> str | None:
    """Return the highest version string, or None when the
    input is empty."""
    if not versions:
        return None
    try:
        return max(versions, key=_parse)
    except Exception:  # noqa: BLE001
        return max(versions)  # best-effort lexical


# ---------------------------------------------------------------------------
# PyPI lookup — the network call
# ---------------------------------------------------------------------------


def latest_pypi_version(
    pkg: str = PACKAGE_NAME,
    *,
    channel: str = "stable",
    timeout: float = _PYPI_TIMEOUT,
) -> str | None:
    """Query PyPI's JSON API for the highest release in the
    requested channel.

    ``channel="stable"`` filters out pre-release versions;
    ``"pre"`` includes them. Returns None on any failure —
    OSError (offline / DNS), HTTPError (404 on package),
    JSONDecodeError (malformed payload). The caller surfaces
    "offline" cleanly without a stack trace.
    """
    url = _PYPI_URL_TEMPLATE.format(pkg=pkg)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            data = json.load(resp)
    except (OSError, urllib.error.URLError, ValueError) as e:
        logger.info("PyPI lookup for %s failed (offline?): %s", pkg, e)
        return None
    releases = data.get("releases") if isinstance(data, dict) else None
    if not isinstance(releases, dict):
        return None
    versions = [v for v in releases.keys() if channel == "pre" or not _is_prerelease(v)]
    return _max_version(versions)


# ---------------------------------------------------------------------------
# git ls-remote for source installs
# ---------------------------------------------------------------------------


def latest_git_tag(
    *,
    repo_root: str | None = None,
    timeout: float = 10.0,
) -> str | None:
    """Run ``git ls-remote --tags origin`` to find the latest
    version tag in the upstream. Best-effort: any subprocess
    failure (git missing, no remote, network unreachable)
    returns None.

    Version tags are detected via a permissive regex —
    ``vX.Y[.Z][...]`` after the last ``/`` in the ref. The
    leading ``v`` is stripped from the returned version so
    comparison with ``athena.__version__`` works.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--tags", "origin"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.info("git ls-remote failed: %s", e)
        return None
    if proc.returncode != 0:
        logger.info("git ls-remote returned %s: %s", proc.returncode, proc.stderr.strip())
        return None
    versions: list[str] = []
    for line in proc.stdout.splitlines():
        # Format: <sha>\trefs/tags/<name>
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        ref = parts[1].rsplit("/", 1)[-1]
        if ref.endswith("^{}"):
            ref = ref[:-3]  # peeled tag
        # Accept v0.2.0 or 0.2.0 shapes.
        match = re.match(r"^v?(\d+(?:\.\d+)+(?:[._-]?\w+)?)$", ref)
        if match:
            versions.append(match.group(1))
    return _max_version(versions)


# ---------------------------------------------------------------------------
# Method-aware dispatch
# ---------------------------------------------------------------------------


def latest_for(
    method: InstallMethod,
    *,
    cfg: Any | None = None,
    pkg: str = PACKAGE_NAME,
) -> str | None:
    """Pick the right "latest" lookup per install method.

    PIP / PIPX → PyPI JSON.
    GIT → ``git ls-remote --tags origin`` on the package's
    repo root.
    EDITABLE → None (the command warns + exits — we don't
    speculate on what the user's editing toward).
    UNKNOWN → None.
    """
    channel = getattr(cfg, "update_channel", "stable") if cfg is not None else "stable"
    if method in (InstallMethod.PIP, InstallMethod.PIPX):
        return latest_pypi_version(pkg, channel=channel)
    if method == InstallMethod.GIT:
        return latest_git_tag()
    return None


# ---------------------------------------------------------------------------
# Changelog preview
# ---------------------------------------------------------------------------


def changelog_between(
    current: str,
    latest: str,
    *,
    method: InstallMethod | None = None,
    changelog_path: str | None = None,
    repo_root: str | None = None,
) -> str:
    """Return a human-readable preview of what changed between
    ``current`` and ``latest``.

    For ``PIP`` / ``PIPX``: read the packaged ``CHANGELOG.md``
    (next to the package root or at ``changelog_path``) and
    extract the section headings ``## [<version>]`` between
    the two versions. When the CHANGELOG isn't found OR the
    sections can't be parsed, fall back to a one-line
    "see https://github.com/... for changes" pointer.

    For ``GIT``: run ``git log v<current>..v<latest> --oneline``
    in ``repo_root`` and return the output. Best-effort —
    subprocess failure returns the same pointer fallback.

    Always returns a non-empty string; the caller renders it
    directly.
    """
    if method == InstallMethod.GIT:
        return _changelog_via_git(current, latest, repo_root=repo_root)
    return _changelog_via_file(current, latest, changelog_path=changelog_path)


def _changelog_via_file(
    current: str,
    latest: str,
    *,
    changelog_path: str | None,
) -> str:
    """Read the on-disk CHANGELOG and slice between the two
    version sections. Uses the standard ``## [<version>]``
    heading shape Keep-a-Changelog projects use; falls back to
    ``## <version>`` if the bracketed form isn't found."""
    path = _resolve_changelog_path(changelog_path)
    if path is None:
        return _pointer_fallback()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return _pointer_fallback()

    # Find every "## [x.y.z]" or "## x.y.z" heading + its line offset.
    headings = _find_version_headings(text)
    if not headings:
        return _pointer_fallback()

    # Build a "from-here-to-there" slice. Start at the heading
    # >= latest and end at the heading <= current. Walks in
    # rendered (file) order: usually newest-first in
    # Keep-a-Changelog, so "[Unreleased]" / latest is near the
    # top and current is further down.
    sections = _slice_between(text, headings, current=current, latest=latest)
    if not sections.strip():
        return _pointer_fallback()
    return sections


def _changelog_via_git(
    current: str,
    latest: str,
    *,
    repo_root: str | None,
) -> str:
    """`git log v<current>..v<latest> --oneline`. Tries with
    and without the v-prefix; the first one that returns
    output wins."""
    for cur_ref, lat_ref in (
        (f"v{current}", f"v{latest}"),
        (current, latest),
    ):
        try:
            proc = subprocess.run(
                ["git", "log", "--oneline", f"{cur_ref}..{lat_ref}"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return _pointer_fallback()
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
    return _pointer_fallback()


def _pointer_fallback() -> str:
    return (
        "Changelog details unavailable locally — see the project's "
        "CHANGELOG for the diff between versions."
    )


def _resolve_changelog_path(explicit: str | None) -> Path | None:
    from pathlib import Path

    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    # Try a few common locations relative to the package.
    from .detect import _package_root

    base = _package_root()
    candidates = [
        base.parent / "CHANGELOG.md",
        base / "CHANGELOG.md",
        base.parent / "CHANGES.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _find_version_headings(text: str) -> list[tuple[int, str]]:
    """Find every heading that names a version. Returns a list
    of ``(line_index, version_string)`` in file order.

    Recognised shapes:
      ``## [1.2.3]``     (Keep-a-Changelog)
      ``## [Unreleased]``  → treated as a heading with version
                            placeholder "unreleased"
      ``## 1.2.3``
      ``## v1.2.3 - 2026-01-01``  (KaC dated)
    """
    out: list[tuple[int, str]] = []
    rx = re.compile(
        r"^##\s+(?:\[([^\]]+)\]|v?(\d+(?:\.\d+)+(?:[._-]?\w+)?))",
        re.MULTILINE,
    )
    for m in rx.finditer(text):
        version = (m.group(1) or m.group(2) or "").strip()
        if version:
            out.append((m.start(), version.lower()))
    return out


def _slice_between(
    text: str,
    headings: list[tuple[int, str]],
    *,
    current: str,
    latest: str,
) -> str:
    """Return the text from the latest's heading down to (but
    not including) the current's heading. If either heading
    isn't found, fall back to "from the latest heading down
    to the end" / "from the first heading to current"."""
    latest_idx: int | None = None
    current_idx: int | None = None

    def norm(v: str) -> str:
        return v.lstrip("v").lower()

    target_latest = norm(latest)
    target_current = norm(current)
    for offset, ver in headings:
        v = norm(ver)
        if v == target_latest and latest_idx is None:
            latest_idx = offset
        if v == target_current and current_idx is None:
            current_idx = offset

    if latest_idx is None:
        # Latest's heading not in the CHANGELOG. Show
        # everything above the current heading instead (best
        # available).
        latest_idx = 0
    if current_idx is None:
        # Current's heading not in the CHANGELOG. Show from
        # latest to end.
        return text[latest_idx:].rstrip()
    if current_idx <= latest_idx:
        # Out-of-order — KaC is usually newest first so
        # current's offset is BIGGER than latest's. Defensive
        # fallback returns the empty string so the caller's
        # pointer fallback fires.
        return ""
    return text[latest_idx:current_idx].rstrip()
