"""``athena update`` — the user-facing self-update command (T6-07.4).

Three flags compose the action surface:

  ``--check``        report current vs latest + the changelog
                     preview. Installs nothing.
  ``--to <version>`` pin to a specific version (up or down).
                     Skips the latest-version lookup.
  ``--rollback``     install the previously-recorded version.
                     Reads ``update_state.json``.

Default (no flag) flow:

  1. Detect install method (pip / pipx / git / editable /
     unknown). REFUSED for editable + unknown — no surprises.
  2. Look up the latest version per the channel
     (cfg.update_channel; default "stable"). Network failure
     → clean "offline" message, no changes.
  3. If not newer → "up to date" and exit.
  4. Render the changelog between current and latest.
  5. Prompt for confirmation. Without a TTY / when --yes
     isn't set we surface the action and exit (the agent
     never auto-installs).
  6. Record the prior version + run the install.
  7. End with "restart athena to use it" — NEVER hot-swap.

Optional startup auto-check (cfg.update_auto_check, default
OFF): one-line notice on launch when a newer version exists.
Notify only; never auto-install. Run on its own short
timeout so a slow PyPI lookup never blocks startup.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from .. import ui

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def _resolve_current_version() -> str:
    """The athena package version we're running under. Falls
    back to "unknown" — the comparison still proceeds (against
    an unknown version, anything compares "newer" → the
    upgrade flow runs, which is the safest default for an
    install with broken metadata)."""
    try:
        from athena import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001
        return "0.0.0"


def _emit_status(label: str, *, kind: str = "info") -> None:
    """Console output wrapper — keeps the command's surface
    consistent and easy to test (capsys captures ui.console
    output reliably)."""
    if kind == "warn":
        ui.warn(label)
    elif kind == "error":
        ui.error(label)
    elif kind == "success":
        ui.console.print(f"[green]{label}[/]")
    else:
        ui.info(label)


def _confirm(question: str, *, assume_yes: bool) -> bool:
    """Ask the user. When --yes was passed OR stdin isn't a
    tty (CI / scripted), refuse to install unless --yes was
    explicitly set — the agent never auto-installs."""
    if assume_yes:
        return True
    try:
        if not sys.stdin.isatty():
            _emit_status(
                "no interactive stdin — pass --yes to proceed; refusing",
                kind="warn",
            )
            return False
    except Exception:  # noqa: BLE001
        return False
    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def _run_check(args: argparse.Namespace, cfg: Any) -> int:
    """The `--check` path. Reports current vs latest +
    changelog; never installs.

    Exit codes:
      0  no update available (or check report rendered)
      0  update available (we don't fail-exit on
         availability — that would be useful in scripts but
         the spec wants `--check` to be report-only with no
         side effects)
    """
    from ..update.check import changelog_between, is_newer, latest_for
    from ..update.detect import detect

    method = detect()
    current = _resolve_current_version()
    _emit_status(f"athena {current} installed via {method.value}")

    latest = latest_for(method, cfg=cfg)
    if latest is None:
        _emit_status(
            "could not reach the update source (offline?); no changes made",
            kind="warn",
        )
        return 0

    if not is_newer(current, latest):
        _emit_status(f"athena {current} is up to date.")
        return 0

    _emit_status(f"update available: {current} → {latest}", kind="success")
    preview = changelog_between(current, latest, method=method)
    ui.console.print("")
    ui.console.print("[bold]Changelog preview[/]")
    ui.console.print(preview)
    ui.console.print("")
    _emit_status(
        "this is a --check report; run `athena update` to install",
    )
    return 0


def _run_install(args: argparse.Namespace, cfg: Any) -> int:
    """Default install flow with confirmation."""
    from ..update.apply import install, record_prior
    from ..update.check import changelog_between, is_newer, latest_for
    from ..update.detect import InstallMethod, detect

    method = detect()
    current = _resolve_current_version()
    _emit_status(f"athena {current} installed via {method.value}")

    if method == InstallMethod.EDITABLE:
        _emit_status(
            "editable install detected — update via your source checkout "
            "(`git pull` + `pip install -e .`). athena update won't "
            "overwrite a developer's working tree.",
            kind="warn",
        )
        return 1
    if method == InstallMethod.UNKNOWN:
        _emit_status(
            "could not detect install method. Run one of: "
            "`pip install --upgrade athena-coder` (pip), "
            "`pipx upgrade athena-coder` (pipx), or "
            "`git pull` + reinstall (source).",
            kind="warn",
        )
        return 1

    # Pinned-version path bypasses the latest-version lookup.
    target = args.to
    if target is None:
        latest = latest_for(method, cfg=cfg)
        if latest is None:
            _emit_status(
                "could not reach the update source (offline?); no changes made",
                kind="warn",
            )
            return 0
        if not is_newer(current, latest):
            _emit_status(f"athena {current} is up to date.")
            return 0
        target = latest
        _emit_status(
            f"update available: {current} → {target}", kind="success"
        )
        preview = changelog_between(current, target, method=method)
        ui.console.print("")
        ui.console.print("[bold]Changelog preview[/]")
        ui.console.print(preview)
        ui.console.print("")
    else:
        _emit_status(f"pinning athena to {target}")

    if not _confirm(
        f"install {target} via {method.value}?",
        assume_yes=bool(args.yes),
    ):
        _emit_status("aborted", kind="warn")
        return 1

    record_prior(current, cfg=cfg)
    result = install(method, version=target, cfg=cfg)
    if not result.succeeded:
        _emit_status(result.message or "install failed", kind="error")
        if result.stderr:
            ui.console.print(result.stderr)
        return 1
    _emit_status(result.message, kind="success")
    return 0


def _run_rollback(args: argparse.Namespace, cfg: Any) -> int:
    """The `--rollback` path. Installs the previously-recorded
    version via the detected method."""
    from ..update.apply import read_prior, rollback as do_rollback

    prior = read_prior(cfg=cfg)
    if prior is None:
        _emit_status(
            "no prior version recorded — run `athena update` once first; "
            "the next rollback will restore that version.",
            kind="warn",
        )
        return 1

    if not _confirm(
        f"roll back to athena {prior}?",
        assume_yes=bool(args.yes),
    ):
        _emit_status("aborted", kind="warn")
        return 1

    result = do_rollback(cfg=cfg)
    if not result.succeeded:
        _emit_status(result.message or "rollback failed", kind="error")
        if result.stderr:
            ui.console.print(result.stderr)
        return 1
    _emit_status(result.message, kind="success")
    return 0


def main(argv: list[str]) -> int:
    """``athena update`` CLI entry."""
    ap = argparse.ArgumentParser(
        prog="athena update",
        description=(
            "Update athena to the latest published release. Detects the "
            "install method (pip / pipx / git / editable) and uses the "
            "matching upgrade path. Off-by-default: requires explicit "
            "confirmation; never hot-swaps the running process."
        ),
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Report current vs latest + changelog preview; install nothing.",
    )
    ap.add_argument(
        "--to",
        default=None,
        metavar="VERSION",
        help="Pin to a specific version (skips the latest-version lookup).",
    )
    ap.add_argument(
        "--rollback",
        action="store_true",
        help="Restore the previously-recorded version.",
    )
    ap.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt (for scripted use).",
    )
    args = ap.parse_args(argv)

    if args.check and args.rollback:
        ap.error("--check and --rollback are mutually exclusive")
    if args.check and args.to:
        ap.error("--check and --to are mutually exclusive")
    if args.rollback and args.to:
        ap.error("--rollback and --to are mutually exclusive")

    from ..config import load_config

    cfg = load_config()

    if args.check:
        return _run_check(args, cfg)
    if args.rollback:
        return _run_rollback(args, cfg)
    return _run_install(args, cfg)


# ---------------------------------------------------------------------------
# Optional startup auto-check
# ---------------------------------------------------------------------------


def startup_notice(cfg: Any) -> None:
    """Called from athena.__main__ at process start. When
    ``cfg.update_auto_check`` is True AND a newer version
    exists on the configured channel, prints a one-line
    notice. Notify only; NEVER auto-installs.

    Bounded by its own short timeout (3s) so startup never
    blocks on a slow PyPI lookup. Any failure is silent —
    the notice is a courtesy, not a feature gate.
    """
    if not bool(getattr(cfg, "update_auto_check", False)):
        return
    try:
        from ..update.check import (
            is_newer,
            latest_pypi_version,
        )
        from ..update.detect import InstallMethod, detect

        method = detect()
        if method in (InstallMethod.UNKNOWN, InstallMethod.EDITABLE):
            return
        # The auto-check always uses the PyPI source (faster
        # than a git ls-remote at every startup). Git users
        # who want startup checks would point update_source
        # at "pypi" anyway.
        latest = latest_pypi_version(
            channel=getattr(cfg, "update_channel", "stable"),
            timeout=3.0,
        )
        if latest is None:
            return
        current = _resolve_current_version()
        if not is_newer(current, latest):
            return
        _emit_status(
            f"athena {latest} is available (current {current}); "
            "run `athena update` to install.",
        )
    except Exception:  # noqa: BLE001
        # Silent — the notice is a courtesy, not a gate.
        logger.debug("auto-check failed", exc_info=True)
