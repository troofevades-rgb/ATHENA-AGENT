"""Mechanical-safety helpers: approval gating, allowlists, snapshot/rollback.

The approval-callback ContextVar lives here from Phase 0 because forks need
to install ``AUTO_DENY`` at thread entry. Phase 17 fills in the rest:
content-addressed snapshots, mutation audit log, ContextVar approval guard,
word-boundary shell policy.
"""
from .audit import MutationAuditLog, MutationRecord, now_iso, sha_of_file
from .context import get_audit_log, get_snapshot_store, reset_for_tests
from .snapshots import Snapshot, SnapshotError, SnapshotStore

__all__ = [
    "MutationAuditLog",
    "MutationRecord",
    "Snapshot",
    "SnapshotError",
    "SnapshotStore",
    "get_audit_log",
    "get_snapshot_store",
    "now_iso",
    "reset_for_tests",
    "sha_of_file",
]
