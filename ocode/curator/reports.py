"""Placeholder for the curator run-report writer. Phase 4 prompt 4.5 fills
this in with run.json + REPORT.md emission. Other modules import write_run
already so the placeholder must conform to the same signature."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_run(
    agent: Any,
    fork_result: Any,
    parsed_yaml: dict,
    *,
    dry_run: bool = False,
    logs_root: Path | None = None,
) -> dict:
    return {
        "decisions": parsed_yaml.get("runs", []),
        "dry_run": dry_run,
    }
