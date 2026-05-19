"""Entry point for ``athena import-from-hermes``.

Composes the per-domain importers. Each importer records into the shared
:class:`~athena.migration.report.Report`; failures inside one phase never
abort the others. The migration always runs under
``write_origin="migration"`` so any frontmatter writes pick up the right
provenance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ..provenance import (
    MIGRATION,
    reset_current_write_origin,
    set_current_write_origin,
)
from . import (
    config_translator,
    mcp_translator,
    memory_exporter,
    sessions_importer,
    skills_mapper,
)
from .report import Report

DEFAULT_DOMAINS: frozenset[str] = frozenset(
    {
        "skills",
        "memory",
        "sessions",
        "config",
        "mcp",
    }
)


def run_import(
    source: Path,
    dest: Path,
    *,
    profile: str = "default",
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    dry_run: bool = False,
    no_confirm: bool = False,
) -> Path:
    """Migrate Hermes data at ``source`` into athena v2 at ``dest``.

    Returns the path to the migration report directory.
    """
    include = set(include or DEFAULT_DOMAINS)
    exclude = set(exclude or set())
    active = include - exclude

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_dir = dest / "logs" / "migration" / stamp
    report = Report(path=report_dir)
    report.add(
        "invocation",
        {
            "source": str(source),
            "dest": str(dest),
            "profile": profile,
            "include": sorted(active),
            "exclude": sorted(exclude),
            "dry_run": dry_run,
        },
    )

    token = set_current_write_origin(MIGRATION)
    try:
        if "skills" in active:
            skills_mapper.import_skills(
                source, dest, profile=profile, report=report, dry_run=dry_run
            )
        if "memory" in active:
            memory_exporter.export_memory(
                source, dest, profile=profile, report=report, dry_run=dry_run
            )
        if "sessions" in active:
            sessions_importer.import_sessions(
                source, dest, profile=profile, report=report, dry_run=dry_run
            )
        if "config" in active:
            config_translator.translate_config(source, dest, report=report, dry_run=dry_run)
        if "mcp" in active:
            mcp_translator.translate_mcp(source, dest, report=report, dry_run=dry_run)
    finally:
        reset_current_write_origin(token)

    report.write()
    return report.path
