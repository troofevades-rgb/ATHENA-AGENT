"""Migration report writer.

Each importer calls ``Report.add(key, value)`` as it goes. At the end the
caller invokes ``write()``, which emits ``REPORT.md`` (human-readable) and
``summary.json`` (structured) into the report directory.

The report is the single source of truth about what happened during an
``ocode import-from-hermes`` run — never raise to abort the whole import on
a per-artifact failure; record it in the report and continue.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Report:
    path: Path
    entries: dict[str, list[Any]] = field(default_factory=lambda: defaultdict(list))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def add(self, key: str, value: Any) -> None:
        """Record an event under ``key``. Values may be any JSON-serializable
        payload (most importers use dicts so the report can render nicely)."""
        self.entries[key].append(value)

    def count(self, key: str) -> int:
        return len(self.entries.get(key, []))

    def write(self) -> Path:
        """Emit REPORT.md and summary.json under :attr:`path`. Returns the
        path to REPORT.md."""
        self.path.mkdir(parents=True, exist_ok=True)
        ended = datetime.now(timezone.utc)
        summary = {
            "started_at": self.started_at.isoformat(),
            "ended_at": ended.isoformat(),
            "duration_seconds": (ended - self.started_at).total_seconds(),
            "counts": {key: len(vals) for key, vals in self.entries.items()},
            "entries": {key: list(vals) for key, vals in self.entries.items()},
        }
        (self.path / "summary.json").write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8"
        )
        (self.path / "REPORT.md").write_text(self._render_markdown(summary), encoding="utf-8")
        return self.path / "REPORT.md"

    def _render_markdown(self, summary: dict[str, Any]) -> str:
        lines = ["# Migration report", ""]
        lines.append(f"- started: {summary['started_at']}")
        lines.append(f"- ended:   {summary['ended_at']}")
        lines.append(f"- duration: {summary['duration_seconds']:.1f}s")
        lines.append("")
        lines.append("## Counts")
        if not summary["counts"]:
            lines.append("(no events)")
        else:
            for key in sorted(summary["counts"]):
                lines.append(f"- {key}: {summary['counts'][key]}")
        lines.append("")
        lines.append("## Details")
        for key in sorted(summary["entries"]):
            lines.append(f"### {key}")
            for v in summary["entries"][key]:
                lines.append(f"- {v}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
