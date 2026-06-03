"""Per-profile singletons for SnapshotStore + MutationAuditLog.

Tools that mutate skills, memory, or workspace files reach for
:func:`get_snapshot_store` / :func:`get_audit_log` so every write
goes through a single store rather than each tool constructing its
own. The stores are keyed by profile root so two concurrent
profiles in the same process see their own snapshot/audit directories.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .audit import MutationAuditLog
from .snapshots import SnapshotStore

_LOCK = threading.Lock()
_SNAPSHOT_STORES: dict[str, SnapshotStore] = {}
_AUDIT_LOGS: dict[str, MutationAuditLog] = {}


def _root_for(profile_dir: Path | None) -> Path:
    """Resolve the storage root. ``None`` means
    ``<current home>/.athena`` — re-computed fresh each call so
    tests that monkeypatch ``Path.home()`` get tmp-scoped stores
    instead of polluting the developer's real home directory."""
    if profile_dir is not None:
        return Path(profile_dir)
    return Path.home() / ".athena"


def get_snapshot_store(profile_dir: Path | None = None) -> SnapshotStore:
    root = _root_for(profile_dir)
    key = str(root.resolve())
    with _LOCK:
        store = _SNAPSHOT_STORES.get(key)
        if store is None:
            # Honor cfg.safety retention policy when the cfg is loadable.
            # Lazy import avoids an upward dep from athena.safety on
            # athena.config at module load. If load_config fails (test
            # fixtures that monkeypatch CONFIG_PATH before importing
            # safety, etc.) we fall back to SnapshotStore's hardcoded
            # defaults, which match SafetyConfig's defaults exactly.
            kwargs: dict[str, Any] = {"root": root / "snapshots"}
            try:
                from ..config import load_config as _load_config

                safety = _load_config().safety
                kwargs["retention_days"] = safety.retention_days
                kwargs["retention_count"] = safety.retention_count
                kwargs["retention_bytes"] = safety.retention_bytes
            except Exception:  # noqa: BLE001
                pass
            store = SnapshotStore(**kwargs)
            _SNAPSHOT_STORES[key] = store
        return store


def get_audit_log(profile_dir: Path | None = None) -> MutationAuditLog:
    root = _root_for(profile_dir)
    key = str(root.resolve())
    with _LOCK:
        log = _AUDIT_LOGS.get(key)
        if log is None:
            log = MutationAuditLog(root / "audit")
            _AUDIT_LOGS[key] = log
        return log


def reset_for_tests() -> None:
    """Test-only: clear the singletons so the next call rebuilds
    against a fresh tmp_path."""
    with _LOCK:
        _SNAPSHOT_STORES.clear()
        _AUDIT_LOGS.clear()
