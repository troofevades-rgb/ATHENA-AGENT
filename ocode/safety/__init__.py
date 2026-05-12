"""Mechanical-safety helpers: approval gating, allowlists, snapshot/rollback.

Most of this subpackage is filled in by Phase 17 (snapshot + rollback). The
approval-callback ContextVar lives here from Phase 0 because forks need it
to install ``AUTO_DENY`` at thread entry.
"""
