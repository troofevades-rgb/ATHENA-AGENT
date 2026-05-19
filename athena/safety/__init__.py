"""Mechanical-safety helpers: approval gating, allowlists, snapshot/rollback.

The approval-callback ContextVar lives here from Phase 0 because forks need
to install ``AUTO_DENY`` at thread entry. Phase 17 fills in the rest:
content-addressed snapshots, mutation audit log, ContextVar approval guard,
word-boundary shell policy.
"""

from .audit import MutationAuditLog, MutationRecord, now_iso, sha_of_file
from .context import get_audit_log, get_snapshot_store, reset_for_tests
from .secure_files import (
    ensure_secure_dir,
    secure_read_json,
    secure_read_text,
    secure_write_json,
    secure_write_text,
)
from .snapshots import Snapshot, SnapshotError, SnapshotStore

__all__ = [
    "MutationAuditLog",
    "MutationRecord",
    "Snapshot",
    "SnapshotError",
    "SnapshotStore",
    "ensure_secure_dir",
    "get_audit_log",
    "get_snapshot_store",
    "now_iso",
    "reset_for_tests",
    "secure_read_json",
    "secure_read_text",
    "secure_write_json",
    "secure_write_text",
    "sha_of_file",
]
