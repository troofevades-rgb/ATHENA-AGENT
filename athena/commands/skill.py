"""``/skill import <path>`` and ``/skill reload`` — in-session skill ingestion.

The CLI form (``athena skill add``) lives in a separate process and just
writes the file; this slash form lands the same install AND triggers
``Agent.reload_skills()`` so the new content becomes visible to the
model without waiting for the next session start.

Subcommands:

  /skill import <path>     install a SKILL.md / dir / archive
  /skill import-workspace  install into <workspace>/.athena/skills/
                           instead of ~/.athena/skills/
  /skill reload            drop the body cache + rebuild the prompt
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import ui
from ..skills.importer import import_archive, import_skill
from . import command


def _is_archive(path: Path) -> bool:
    if not path.is_file():
        return False
    suffix = path.suffix.lower()
    if suffix in (".zip", ".tgz", ".tar"):
        return True
    return "".join(path.suffixes[-2:]).lower().endswith(".tar.gz")


@command("skill")
def cmd_skill(agent: Any, arg: str = "") -> str:
    parts = (arg or "").strip().split(maxsplit=1)
    if not parts:
        ui.error("usage: /skill import <path> | /skill import-workspace <path> | /skill reload")
        return ""
    verb = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if verb == "reload":
        agent.reload_skills()
        ui.info("skill catalog reloaded")
        return ""

    if verb in ("import", "import-workspace"):
        if not rest:
            ui.error(f"usage: /skill {verb} <path>")
            return ""
        source = Path(rest.strip().strip('"').strip("'")).expanduser()
        if not source.exists():
            ui.error(f"path does not exist: {source}")
            return ""
        if verb == "import-workspace":
            base = agent.workspace / ".athena" / "skills"
        else:
            base = Path.home() / ".athena" / "skills"

        # Always pass on_conflict="abort" from the slash — the operator
        # can re-run with the CLI for overwrite/rename. Keeping the
        # in-session form non-destructive matches the safety posture
        # the rest of the slash commands take.
        if _is_archive(source):
            result = import_archive(source, base=base, on_conflict="abort")
        else:
            result = import_skill(source, base=base, on_conflict="abort")

        if result.status == "rejected":
            ui.error("skill import rejected")
            for e in result.errors:
                ui.console.print(f"  [red]- {e}[/]")
            return ""
        if result.status == "skipped":
            ui.warn(
                f"{result.name!r} already exists at {result.dest}. "
                "Re-run with `athena skill add --overwrite` or `--rename` to replace it."
            )
            return ""
        # Refresh the running session so the new skill is immediately visible.
        agent.reload_skills()
        ui.info(f"{result.status}: {result.name} -> {result.dest}")
        return ""

    ui.error(f"unknown /skill subcommand: {verb!r}")
    return ""
