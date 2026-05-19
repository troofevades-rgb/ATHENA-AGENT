"""Migrate Hermes memory entries into athena v2's per-file memory format.

Hermes stores memory in a SQLite ``memory.db`` with table ``memory_entries``
(columns: ``id, profile, name, type, description, body, write_origin,
created_at, last_used_at``). athena v2 stores each entry as a Markdown file
under ``<dest>/profiles/<profile>/memory/<slug>.md`` with the same
frontmatter shape we use everywhere (name, type, description,
write_origin, created_at, last_used_at).

Honcho / Mem0 / byterover providers are not directly readable — when we
detect those (via ``<source>/memory_provider``) we record a WARNING in
the report and exit the memory phase without writing anything.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .report import Report

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    s = _NON_SLUG.sub("_", name.lower()).strip("_")
    return s or "memory"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    return str(value)


def _detect_unknown_provider(source: Path) -> str | None:
    """Return a non-SQLite provider name if Hermes is configured to use one."""
    marker = source / "memory_provider"
    if marker.exists():
        provider = marker.read_text(encoding="utf-8").strip().lower()
        if provider not in ("", "sqlite"):
            return provider
    return None


def _read_rows(db_path: Path) -> Iterable[dict[str, Any]]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(
            "SELECT id, profile, name, type, description, body, write_origin, "
            "created_at, last_used_at FROM memory_entries"
        )
        for r in cur:
            yield dict(r)
    finally:
        con.close()


def _write_memory_md(target: Path, row: dict[str, Any]) -> None:
    """Emit a single memory file with YAML frontmatter + body."""
    fm_lines: list[str] = ["---"]
    fm_lines.append(f"name: {row['name']}")
    if row.get("type"):
        fm_lines.append(f"type: {row['type']}")
    if row.get("description"):
        fm_lines.append(f"description: {row['description']}")
    fm_lines.append("write_origin: migration")
    created = _iso(row.get("created_at"))
    last = _iso(row.get("last_used_at"))
    if created:
        fm_lines.append(f"created_at: {created}")
    if last:
        fm_lines.append(f"last_used_at: {last}")
    fm_lines.append("---")
    body = row.get("body") or ""
    target.write_text(
        "\n".join(fm_lines) + "\n" + body + ("\n" if not body.endswith("\n") else ""),
        encoding="utf-8",
    )


def _rebuild_index(memory_dir: Path) -> None:
    """Walk the memory directory and write a fresh MEMORY.md index."""
    rows: list[str] = []
    for md_file in sorted(memory_dir.glob("*.md")):
        if md_file.name.lower() == "memory.md":
            continue
        rows.append(f"- [{md_file.stem}]({md_file.name})")
    (memory_dir / "MEMORY.md").write_text(
        "# Memory index\n\n" + ("\n".join(rows) if rows else "(no entries)") + "\n",
        encoding="utf-8",
    )


def export_memory(
    source: Path,
    dest: Path,
    *,
    profile: str = "default",
    report: Report,
    dry_run: bool = False,
) -> None:
    """Read Hermes memory.db and write per-row Markdown files at the destination."""
    unknown = _detect_unknown_provider(source)
    if unknown is not None:
        report.add(
            "memory_warning",
            {
                "reason": "unsupported_provider",
                "provider": unknown,
                "message": (
                    f"Hermes is configured with memory provider {unknown!r}; "
                    "athena v2 cannot read it directly. Export manually."
                ),
            },
        )
        return

    db_path = source / "memory.db"
    if not db_path.exists():
        report.add(
            "memory_warning",
            {
                "reason": "no_db",
                "path": str(db_path),
                "message": "no memory.db at Hermes source; skipping memory phase",
            },
        )
        return

    target_dir = dest / "profiles" / profile / "memory"
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for row in _read_rows(db_path):
        row_profile = row.get("profile") or profile
        out_dir = dest / "profiles" / row_profile / "memory"
        if not dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{_slug(row['name'])}.md"
        if not dry_run:
            _write_memory_md(target, row)
        written += 1
        report.add(
            "imported_memory",
            {
                "name": row.get("name"),
                "type": row.get("type"),
                "profile": row_profile,
                "destination": str(target),
                "dry_run": dry_run,
            },
        )

    if not dry_run:
        # Rebuild MEMORY.md per profile we just wrote into.
        seen_profiles = {entry["profile"] for entry in report.entries.get("imported_memory", [])}
        for p in seen_profiles:
            _rebuild_index(dest / "profiles" / p / "memory")

    report.add("memory_summary", {"rows_processed": written, "dry_run": dry_run})
