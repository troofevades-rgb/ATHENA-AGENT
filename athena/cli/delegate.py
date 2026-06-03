"""``athena delegate {verify,setup-codex}`` — CLI delegation admin.

Two subcommands:

  athena delegate verify
    Sanity-check the current ``cli_delegate_command`` config.
    Splits the template via shlex, checks the first token
    (the binary) is on PATH, captures its --version. Tells
    the operator what's wrong if anything is.

  athena delegate setup-codex
    First-time wiring: detect codex on this host + (with
    confirmation) append the canonical config snippet to
    ``~/.athena/config.toml``. A 30-second setup for the most
    common delegate target.

Both subcommands write to stdout; ``--json`` for machine-
readable output (matches the rest of athena's CLI surface).
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from ..config import load_config


def _verify_command(template: str | None) -> dict[str, Any]:
    """Inspect a ``cli_delegate_command`` template, return a
    structured verdict."""
    if not template:
        return {
            "ok": False,
            "reason": (
                "cli_delegate_command is not configured. Run "
                "`athena delegate setup-codex` for the most "
                "common wire-up, or set it manually in "
                "~/.athena/config.toml"
            ),
        }
    try:
        parts = shlex.split(template)
    except ValueError as e:
        return {
            "ok": False,
            "reason": f"cli_delegate_command failed shlex parse: {e}",
        }
    if not parts:
        return {"ok": False, "reason": "cli_delegate_command is empty"}
    binary = parts[0]
    location = shutil.which(binary)
    if location is None:
        return {
            "ok": False,
            "binary": binary,
            "location": None,
            "reason": (
                f"binary {binary!r} not found on PATH. Install it "
                "or fix the cli_delegate_command template."
            ),
        }
    # Best-effort version capture (some binaries don't have
    # --version; we don't fail if it doesn't respond).
    import subprocess

    version = None
    try:
        out = subprocess.run(
            [location, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            version = out.stdout.strip().splitlines()[0]
    except (subprocess.TimeoutExpired, OSError):
        version = None
    return {
        "ok": True,
        "binary": binary,
        "location": location,
        "version": version,
        "template": template,
    }


def cmd_verify(args: argparse.Namespace) -> int:
    cfg = load_config()
    enabled = bool(getattr(cfg, "cli_delegate_enabled", False))
    template = getattr(cfg, "cli_delegate_command", None)
    sandbox = bool(getattr(cfg, "cli_delegate_sandbox", True))

    verdict = _verify_command(template)
    payload = {
        "enabled": enabled,
        "sandbox": sandbox,
        **verdict,
    }
    if args.json:
        sys.stdout.write(json.dumps(payload) + "\n")
    else:
        if not enabled:
            sys.stdout.write("cli_delegate_enabled = false\n")
        if verdict["ok"]:
            sys.stdout.write(
                f"OK  binary={verdict['binary']}  "
                f"location={verdict['location']}  "
                f"version={verdict.get('version') or '?'}\n"
                f"    template={verdict['template']}\n"
                f"    sandbox={sandbox}\n"
            )
            if not enabled:
                sys.stdout.write(
                    "    (note: cli_delegate_enabled=false — set it to true to actually delegate)\n"
                )
        else:
            sys.stdout.write(f"FAIL  {verdict['reason']}\n")

    return 0 if verdict["ok"] and enabled else 1


def cmd_setup_codex(args: argparse.Namespace) -> int:
    """First-time codex wiring: detect + (with confirmation)
    write the canonical config snippet."""
    from ..delegate.codex import (
        detect_codex,
        recommended_config_snippet,
        write_config_snippet,
    )

    detection = detect_codex()

    if not detection.found:
        if args.json:
            sys.stdout.write(
                json.dumps(
                    {
                        "found": False,
                        "error": detection.error,
                    }
                )
                + "\n"
            )
        else:
            sys.stdout.write(f"codex NOT found on PATH.\n\n{detection.error}\n")
        return 1

    if args.detect_only:
        if args.json:
            sys.stdout.write(
                json.dumps(
                    {
                        "found": True,
                        "path": detection.path,
                        "version": detection.version,
                    }
                )
                + "\n"
            )
        else:
            sys.stdout.write(
                f"codex found\n"
                f"  path:    {detection.path}\n"
                f"  version: {detection.version or '(unknown)'}\n"
            )
        return 0

    sandbox = not args.no_sandbox
    snippet = recommended_config_snippet(sandbox=sandbox)

    if args.dry_run:
        if args.json:
            sys.stdout.write(
                json.dumps(
                    {
                        "found": True,
                        "path": detection.path,
                        "version": detection.version,
                        "would_write": snippet,
                    }
                )
                + "\n"
            )
        else:
            sys.stdout.write(
                f"codex found at {detection.path}\n"
                f"(dry-run; would append the following to "
                f"~/.athena/config.toml)\n\n{snippet}"
            )
        return 0

    # Confirmation unless --yes.
    if not args.yes:
        sys.stdout.write(
            f"codex found at {detection.path} (version "
            f"{detection.version or 'unknown'}).\n\n"
            f"Will append the following to {args.config_path or '~/.athena/config.toml'}:\n\n"
            f"{snippet}\n"
            f"Proceed? [y/N] "
        )
        sys.stdout.flush()
        try:
            ans = input().strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            sys.stdout.write("aborted.\n")
            return 0

    try:
        written = write_config_snippet(
            config_path=args.config_path,
            sandbox=sandbox,
            overwrite=args.overwrite,
        )
    except RuntimeError as e:
        if args.json:
            sys.stdout.write(json.dumps({"error": str(e)}) + "\n")
        else:
            sys.stdout.write(f"ERROR: {e}\n")
        return 2

    if args.json:
        sys.stdout.write(
            json.dumps(
                {
                    "found": True,
                    "path": detection.path,
                    "version": detection.version,
                    "wrote": str(written),
                }
            )
            + "\n"
        )
    else:
        sys.stdout.write(
            f"OK  config updated at {written}\n"
            f"    next: restart athena (so the new config takes effect) "
            f"and try `delegate_to_cli` on a small task to verify.\n"
        )
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="athena delegate",
        description="CLI delegation admin (verify config; setup codex).",
    )
    sub = p.add_subparsers(dest="cmd")

    pv = sub.add_parser(
        "verify",
        help="Sanity-check the current cli_delegate_command config.",
    )
    pv.add_argument("--json", action="store_true", help="Machine-readable output.")
    pv.set_defaults(func=cmd_verify)

    ps = sub.add_parser(
        "setup-codex",
        help="Detect codex + append the canonical config snippet.",
    )
    ps.add_argument(
        "--config-path",
        help="Override the config file path (default ~/.athena/config.toml).",
    )
    ps.add_argument(
        "--no-sandbox",
        action="store_true",
        help=(
            "Disable cli_delegate_sandbox (skip the T5-02 bwrap "
            "wrap). Only do this if you understand the risk."
        ),
    )
    ps.add_argument(
        "--detect-only",
        action="store_true",
        help="Just detect codex; don't write any config.",
    )
    ps.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be written; don't actually write.",
    )
    ps.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Proceed even when cli_delegate_command is already "
            "configured. The snippet is APPENDED; existing keys "
            "are not removed (TOML last-value-wins). Review with "
            "a real diff afterwards."
        ),
    )
    ps.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    ps.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output.",
    )
    ps.set_defaults(func=cmd_setup_codex)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    return args.func(args)
