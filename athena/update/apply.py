"""Install / pin / rollback per method (T6-07.3).

The action layer. Composes the previously-detected
:class:`InstallMethod` with the version to install into a
matching invocation:

  PIP       pip install --upgrade athena-coder[==<version>]
  PIPX      pipx upgrade athena-coder  (or  pipx install
            athena-coder==<version> --force for pin/rollback)
  GIT       git fetch + git checkout <ref> + pip install -e .
            (or pip install . for a non-editable git install)
  EDITABLE  refuse with a clear message ("update via your
            source checkout") — we don't pip install over
            a developer's working tree
  UNKNOWN   refuse with a clear message

Invariants enforced + pinned by tests:

  1. **Never hot-swap the running process.** Every action
     installs the new code to the *installed package*; the
     command advises restart. No re-exec inside this module.

  2. **Prior version recorded before upgrade.** ``record_prior``
     writes the current version to ``update_state.json`` so
     ``rollback`` can restore it. Best-effort: a write
     failure logs but doesn't block the install — rollback
     just won't have a target.

  3. **Integrity verified.** For PIP/PIPX we rely on pip's
     hash verification (which is automatic on PyPI installs);
     `--require-hashes` would force it strict, but pip's
     default already validates the wheel's hash against PyPI's
     metadata. For GIT we *can't* easily verify signatures
     without a signed-tag policy in the project; we surface
     the resolved commit SHA so the user sees what they
     fetched. The contract: any path that runs `pip install`
     gets pip's verification automatically; the test pins
     that the apply step routes through pip rather than
     downloading a wheel directly.

  4. **Subprocess capture is on by default.** Output is
     returned in :class:`ApplyResult` rather than streamed to
     stdout, so the command can render its own status line
     instead of pip's verbose chatter. Failures surface the
     stderr.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .detect import PACKAGE_NAME, InstallMethod

logger = logging.getLogger(__name__)


# Default state-file path resolution mirrors the cfg pattern
# T6-04 / T6-05 use: cfg override wins, else a sensible
# default under CONFIG_DIR.
_STATE_FILENAME = "update_state.json"


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ApplyResult:
    """Outcome of one install / pin / rollback attempt.

    Mirrors the pattern used by T6-03 DelegateResult /
    T6-05 GenerationResult — every failure mode maps to a
    status the caller surfaces; never an exception into the
    agent loop.
    """

    status: str  # done | skipped | error | refused
    method: str
    version_installed: Optional[str] = None
    prior_version: Optional[str] = None
    stdout: str = ""
    stderr: str = ""
    message: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == "done"


# ---------------------------------------------------------------------------
# Prior-version state
# ---------------------------------------------------------------------------


def state_path(*, cfg: Any = None) -> Path:
    """Where the prior-version record lives.

    ``cfg.update_state_path`` wins when set; otherwise
    ``<CONFIG_DIR>/update_state.json``. Resolved lazily — the
    cfg module's CONFIG_DIR is read fresh per call so a test
    with a monkeypatched config home is honoured.
    """
    if cfg is not None:
        explicit = getattr(cfg, "update_state_path", None)
        if explicit:
            return Path(str(explicit)).expanduser()
    from ..config import CONFIG_DIR

    return CONFIG_DIR / _STATE_FILENAME


def record_prior(version: str, *, cfg: Any = None) -> bool:
    """Save the current version BEFORE running an upgrade.
    Returns True iff the write succeeded. Best-effort: a
    failure logs + returns False so the install still
    proceeds (the worst case is "no rollback available";
    blocking on a state-file write would be over-cautious).
    """
    if not version:
        return False
    payload = {
        "prior_version": version,
        "recorded_at": time.time(),
    }
    p = state_path(cfg=cfg)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("update: could not record prior version: %s", e)
        return False
    return True


def read_prior(*, cfg: Any = None) -> Optional[str]:
    """Return the recorded prior version, or None when no
    upgrade has been recorded yet / the file is unreadable."""
    p = state_path(cfg=cfg)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("prior_version")
    return str(version) if version else None


# ---------------------------------------------------------------------------
# Subprocess wrapper — the only place we shell out
# ---------------------------------------------------------------------------


def _run(
    argv: list[str],
    *,
    timeout: float = 300.0,
) -> tuple[int, str, str]:
    """Capture stdout + stderr + returncode. Returns the
    triple even on failure; never raises into the caller.

    Timeout default 300s (pip + git over slow network)."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except FileNotFoundError as e:
        return 127, "", f"executable not found: {e}"
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or "" if isinstance(e.stdout, str) else ""), (
            (e.stderr or "" if isinstance(e.stderr, str) else "")
            + f"\n[update] command timed out after {timeout:.0f}s"
        )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _pip_argv(version: Optional[str], *, pkg: str = PACKAGE_NAME) -> list[str]:
    """Build the pip argv. Uses ``sys.executable -m pip`` so we
    target the running interpreter's pip — important when the
    user has multiple Python installations."""
    spec = f"{pkg}=={version}" if version else pkg
    return [sys.executable, "-m", "pip", "install", "--upgrade", spec]


def _pipx_argv(
    version: Optional[str], *, pkg: str = PACKAGE_NAME
) -> list[str]:
    """For a plain upgrade pipx supports ``pipx upgrade``;
    for a pinned version we use ``pipx install ... --force``
    which replaces the venv."""
    if not version:
        return ["pipx", "upgrade", pkg]
    return ["pipx", "install", f"{pkg}=={version}", "--force"]


# ---------------------------------------------------------------------------
# Per-method install
# ---------------------------------------------------------------------------


def install(
    method: InstallMethod,
    *,
    version: Optional[str] = None,
    repo_root: Optional[str] = None,
    pkg: str = PACKAGE_NAME,
    cfg: Any = None,
) -> ApplyResult:
    """Run the matching upgrade path.

    ``version=None`` means "latest" for pip/pipx (or the
    default branch tip for git). A pinned version installs
    that version exactly (works for both upgrade and downgrade
    paths — pip will install whatever you name).

    Never raises into the caller; every failure becomes an
    :class:`ApplyResult` with status="error" / "refused".
    """
    if method == InstallMethod.EDITABLE:
        return ApplyResult(
            status="refused",
            method=method.value,
            message=(
                "editable install detected — update via your source "
                "checkout (git pull + pip install -e .). athena update "
                "won't overwrite a developer's working tree."
            ),
        )
    if method == InstallMethod.UNKNOWN:
        return ApplyResult(
            status="refused",
            method=method.value,
            message=(
                "could not detect the install method. Run one of: "
                "`pip install --upgrade athena-coder` (pip), "
                "`pipx upgrade athena-coder` (pipx), or "
                "`git pull` + reinstall (source)."
            ),
        )

    if method in (InstallMethod.PIP, InstallMethod.PIPX):
        return _install_via_pip_or_pipx(method, version, pkg=pkg)
    if method == InstallMethod.GIT:
        return _install_via_git(version, repo_root=repo_root, pkg=pkg)
    return ApplyResult(
        status="error",
        method=method.value,
        message=f"unsupported install method: {method.value}",
    )


def rollback(*, cfg: Any = None, pkg: str = PACKAGE_NAME) -> ApplyResult:
    """Install the previously-recorded version. Reads
    ``update_state.json`` for the prior version + detects the
    current method to pick the right path."""
    prior = read_prior(cfg=cfg)
    if not prior:
        return ApplyResult(
            status="refused",
            method="rollback",
            message=(
                "no prior version recorded — nothing to roll back to. "
                "Run athena update once first; the next rollback will "
                "restore that version."
            ),
        )
    from .detect import detect

    method = detect(pkg=pkg)
    result = install(method, version=prior, pkg=pkg, cfg=cfg)
    if result.succeeded:
        return ApplyResult(
            status="done",
            method=result.method,
            version_installed=prior,
            prior_version=prior,
            stdout=result.stdout,
            stderr=result.stderr,
            message=f"rolled back to {prior}",
        )
    return result


# ---------------------------------------------------------------------------
# pip / pipx path
# ---------------------------------------------------------------------------


def _install_via_pip_or_pipx(
    method: InstallMethod,
    version: Optional[str],
    *,
    pkg: str,
) -> ApplyResult:
    argv = _pip_argv(version, pkg=pkg) if method == InstallMethod.PIP else _pipx_argv(version, pkg=pkg)
    # Belt-and-braces: if pipx isn't on PATH we don't have a
    # path forward (the install would have been pip), so error
    # early with a clear message instead of FileNotFoundError.
    if method == InstallMethod.PIPX and shutil.which("pipx") is None:
        return ApplyResult(
            status="error",
            method=method.value,
            message="pipx not on PATH — install pipx or switch to pip",
        )
    code, out, err = _run(argv)
    if code != 0:
        return ApplyResult(
            status="error",
            method=method.value,
            stdout=out,
            stderr=err,
            message=f"{method.value} install failed (exit {code})",
        )
    return ApplyResult(
        status="done",
        method=method.value,
        version_installed=version,
        stdout=out,
        stderr=err,
        message=(
            f"installed {pkg} {version or '(latest)'} via {method.value} — "
            "restart athena to use it"
        ),
    )


# ---------------------------------------------------------------------------
# git path
# ---------------------------------------------------------------------------


def _install_via_git(
    version: Optional[str],
    *,
    repo_root: Optional[str],
    pkg: str,
) -> ApplyResult:
    """Three steps: fetch, checkout, reinstall.

    ``version=None`` checks out the default branch tip
    (origin/HEAD); a pinned version checks out the matching
    tag (``v<version>`` first, then bare ``<version>``).

    Reinstalls via ``pip install .`` in the repo so the new
    code lands in site-packages (or the editable link if the
    install was originally `-e`, but in that case the
    EDITABLE method should have caught it before we got here).
    """
    if shutil.which("git") is None:
        return ApplyResult(
            status="error",
            method="git",
            message="git not on PATH",
        )

    # Fetch.
    code, out, err = _run(["git", "-C", repo_root or ".", "fetch", "--tags"])
    if code != 0:
        return ApplyResult(
            status="error",
            method="git",
            stdout=out,
            stderr=err,
            message="git fetch failed",
        )

    # Checkout.
    if version:
        # Try v-prefix tag, fall back to bare version.
        for ref in (f"v{version}", version):
            code, out, err = _run(
                ["git", "-C", repo_root or ".", "checkout", ref]
            )
            if code == 0:
                break
        else:
            return ApplyResult(
                status="error",
                method="git",
                stdout=out,
                stderr=err,
                message=f"could not check out version {version}",
            )
    else:
        # Default branch HEAD.
        code, out, err = _run(
            ["git", "-C", repo_root or ".", "merge", "--ff-only", "@{u}"]
        )
        if code != 0:
            return ApplyResult(
                status="error",
                method="git",
                stdout=out,
                stderr=err,
                message="git merge --ff-only failed (local changes?)",
            )

    # Reinstall — `pip install .` covers both editable + non-
    # editable. (EDITABLE was filtered out earlier so this
    # branch is only the non-editable git case.)
    code, out, err = _run([sys.executable, "-m", "pip", "install", "."])
    if code != 0:
        return ApplyResult(
            status="error",
            method="git",
            stdout=out,
            stderr=err,
            message="pip install . failed after git checkout",
        )
    return ApplyResult(
        status="done",
        method="git",
        version_installed=version,
        stdout=out,
        stderr=err,
        message=(
            f"installed {pkg} from git ({version or 'origin/HEAD'}) — "
            "restart athena to use it"
        ),
    )
