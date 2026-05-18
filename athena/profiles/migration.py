"""One-time migration: legacy flat layout → profile-aware layout.

Earlier athena releases stored everything at the top of
``~/.athena/`` (skills, memory, sessions, …). The multi-profile
release moves those into ``~/.athena/profiles/default/`` so users
running the upgraded binary against a populated old home have
everything land in the right place automatically.

Detection: legacy items exist at ``~/.athena/<x>`` AND
``~/.athena/profiles/`` doesn't exist yet. After the first
successful migration the latter condition fails permanently, so the
check is naturally idempotent.

Per-item failures don't abort: each move runs under its own try; a
failure logs and skips that one item so the rest still migrate. The
user can finish the move by hand for the holdout.

Items that stay at ``~/.athena/`` (user-global, not profile-scope):
``credentials.json``, ``mcp_tokens/``, ``plugins/``, ``logs/``,
``plugins_state.json``, plus the new profile machinery
(``profiles/``, ``active_profile``).
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import CONFIG_DIR
from .resolution import DEFAULT_PROFILE, PROFILES_DIR, ensure_profile

logger = logging.getLogger(__name__)


# Items that belong inside a profile after migration. Both files and
# directories. Ordered for deterministic logging.
_PROFILE_ITEMS: tuple[str, ...] = (
    "skills",
    "memory",
    "sessions",
    "sessions.db",
    "mcp.json",
    "goal.txt",
    "cron.db",
    "cron_jobs.db",
    "gateway.db",
    "gateway_routes.db",
    "gateway_attachments",
    "matrix_store",
    "training_state.json",
    "labels",
    "datasets",
    "models",
    "config.toml",
)

# Items that explicitly stay at ``~/.athena/``. Used to verify the
# inverse condition in tests; not consulted by the migration itself
# (the migration only acts on _PROFILE_ITEMS).
_GLOBAL_ITEMS: frozenset[str] = frozenset({
    "credentials.json",
    "mcp_tokens",
    "plugins",
    "plugins_state.json",
    "logs",
    "profiles",
    "active_profile",
    "memory",  # the providers dir lives under profile/memory/
})


def migration_needed(home: Path | None = None) -> bool:
    """True iff any legacy item exists at the top of ``home`` and
    ``profiles/`` doesn't yet.

    The double condition is the canonical idempotency guard: once
    ``profiles/`` exists (because a prior migration succeeded or
    because the user ran on a fresh install), this returns False
    permanently.
    """
    base = home or CONFIG_DIR
    if (base / "profiles").exists():
        return False
    return any((base / item).exists() for item in _PROFILE_ITEMS)


def run_migration(home: Path | None = None) -> dict[str, list[str]]:
    """Move legacy items into ``profiles/default/``.

    Returns a summary dict ``{moved: [...], failed: [...]}`` for
    logging / observability. Always ensures the default profile's
    bootstrap layout exists at the end, even if nothing moved (so
    subsequent code can rely on the directories being there).
    """
    base = home or CONFIG_DIR
    moved: list[str] = []
    failed: list[str] = []

    target = base / "profiles" / DEFAULT_PROFILE
    target.mkdir(parents=True, exist_ok=True)

    for item in _PROFILE_ITEMS:
        src = base / item
        if not src.exists():
            continue
        dst = target / item
        if dst.exists():
            # Defensive: if the target already has a file by this name,
            # don't clobber. Most likely a partial / re-run scenario;
            # log so the user can resolve manually.
            logger.warning(
                "migration: %s already exists at %s; skipping",
                item, dst,
            )
            failed.append(item)
            continue
        try:
            shutil.move(str(src), str(dst))
            moved.append(item)
        except Exception:
            logger.exception("migration: failed to move %s", item)
            failed.append(item)

    # Ensure the bootstrap layout regardless of what moved — fresh-
    # install users get the same directory layout as migrated ones.
    ensure_profile(DEFAULT_PROFILE)

    if moved or failed:
        logger.info(
            "profile migration: moved %d item(s), %d failure(s) "
            "to ~/.athena/profiles/%s/",
            len(moved), len(failed), DEFAULT_PROFILE,
        )
    return {"moved": moved, "failed": failed}


def maybe_run_migration(home: Path | None = None) -> bool:
    """Convenience wrapper: check + run + return ``True`` iff
    migration happened. Used by ``athena.__main__`` so every
    invocation triggers exactly one migration on the first run after
    upgrade."""
    if not migration_needed(home):
        return False
    run_migration(home)
    return True
