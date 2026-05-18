"""Phase 17.5 — guard against new raw write sites in athena/.

Every agent-driven mutation should route through
:mod:`athena.safety.mutation` (which snapshots + audits). This test
holds the line at today's surface: the set of athena modules that
still call ``Path.write_text`` / ``Path.write_bytes`` / ``open(...,
"w")`` is frozen as an explicit allowlist. New code that introduces
an unblessed raw write fails this test until either the call is
routed through ``snapshot_and_record`` or the module is added to
the allowlist with a one-line justification.

When you genuinely need to add a module: prefer routing through
``snapshot_and_record``. Only add to the allowlist when the write
is a non-mutation (cache files, append-only logs, atomic config
writes that are themselves the audit substrate).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ATHENA_ROOT = REPO_ROOT / "athena"

# Modules whose raw writes are intentional and not subject to the
# snapshot+audit rule. Each entry is a path relative to the repo
# root. Frozen as of Phase 17.5 commit.
ALLOWLIST: frozenset[str] = frozenset({
    "athena/__main__.py",                         # CLI entry; doesn't mutate user content
    "athena/agent/core.py",                       # status snapshot writer (atomic JSON view)
    "athena/cli/train.py",                        # trainer dumps datasets to disk
    "athena/config.py",                           # atomic config writes
    "athena/cron/delivery.py",                    # cron task state journal
    "athena/curator/reports.py",                  # curator emits its own report files
    "athena/gateway/platforms/imessage.py",       # platform-local message buffers
    "athena/gateway/platforms/signal.py",         # platform-local message buffers
    "athena/gateway/platforms/slack.py",          # platform-local message buffers
    "athena/goal/invariant.py",                   # invariant register (append-only)
    "athena/mcp/oauth.py",                        # atomic OAuth token file
    "athena/memory/providers/builtin_file.py",    # public writes routed through snapshot; helpers refresh index
    "athena/migration/config_translator.py",      # one-shot hermes->athena migration
    "athena/migration/mcp_translator.py",         # one-shot hermes->athena migration
    "athena/migration/memory_exporter.py",        # exports legacy memory to disk
    "athena/migration/report.py",                 # migration report
    "athena/migration/sessions_importer.py",      # imports legacy sessions
    "athena/migration/skills_mapper.py",          # one-shot hermes->athena migration
    "athena/plugins/bundled/shell_audit/plugin.py",  # shell audit log (append-only)
    "athena/plugins/loader.py",                   # plugin state file
    "athena/profiles/manager.py",                 # atomic profile metadata writes
    "athena/profiles/resolution.py",              # active-profile pointer
    "athena/safety/audit.py",                     # the audit log itself
    "athena/safety/snapshots.py",                 # the snapshot store itself
    "athena/sessions/jsonl.py",                   # session transcript append
    "athena/sessions/reindex.py",                 # session index rebuild
    "athena/sessions/store.py",                   # session meta writes
    "athena/skills/archive.py",                   # invoked by skill_delete (audited)
    "athena/skills/manager.py",                   # the snapshot site
    "athena/skills/pin.py",                       # invoked by skill_pin (foreground-only)
    "athena/skills/state_machine.py",             # skill state transitions
    "athena/tools/file_ops.py",                   # foreground Read/Edit/Write tools
    "athena/transform/dataset.py",                # training dataset exports
    "athena/transform/deploy.py",                 # deployment artefacts
    "athena/transform/review.py",                 # review artefacts
    "athena/webhooks/delivery.py",                # webhook delivery journal
    # Rollback CLI is itself audited; the restore() call lives in
    # snapshots.py which is allowlisted as the substrate.
    "athena/cli/rollback.py",
})


_PATTERNS = [
    re.compile(r"\.write_text\("),
    re.compile(r"\.write_bytes\("),
    re.compile(r"\bopen\s*\([^)]*['\"][wa][bt]?['\"]"),
    re.compile(r"shutil\.copy"),
    re.compile(r"shutil\.rmtree"),
]


def _iter_python_files(root: Path):
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        if p.name == "__init__.py":
            continue
        yield p


def _module_key(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def test_no_new_raw_write_sites_outside_allowlist() -> None:
    """New raw writes in athena/ must either be routed through
    ``snapshot_and_record`` or explicitly added to ALLOWLIST."""
    new_violators: set[str] = set()
    for py in _iter_python_files(ATHENA_ROOT):
        rel = _module_key(py)
        if rel in ALLOWLIST:
            continue
        text = py.read_text(encoding="utf-8")
        for pattern in _PATTERNS:
            if pattern.search(text):
                new_violators.add(rel)
                break

    assert not new_violators, (
        "New raw write sites found in athena/ that aren't in the "
        "snapshot+audit allowlist. Either route the write through "
        "athena.safety.mutation.snapshot_and_record, or add the "
        "module to ALLOWLIST in test_no_raw_writes.py with a "
        "justification.\n\n"
        f"Violators:\n  " + "\n  ".join(sorted(new_violators))
    )


def test_allowlist_entries_all_exist() -> None:
    """No phantom allowlist entries — if a module was renamed or
    deleted, prune the allowlist."""
    missing: list[str] = []
    for rel in ALLOWLIST:
        if not (REPO_ROOT / rel).exists():
            missing.append(rel)
    assert not missing, (
        "Allowlist references modules that don't exist:\n  "
        + "\n  ".join(sorted(missing))
    )
