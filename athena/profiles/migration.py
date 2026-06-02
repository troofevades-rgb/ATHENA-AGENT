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
``mcp_tokens/``, ``plugins/``, ``logs/``, ``plugins_state.json``, plus
the new profile machinery (``profiles/``, ``active_profile``).

``credentials.json`` is NOT moved by this migration even though
credentials are now profile-scoped: ``credential_pool.profile_pool``
seeds the ``default`` profile from the legacy global file lazily on
first access (a copy), so this one-shot mover would race that and risk
clobbering. The legacy global file is left in place and becomes
vestigial once ``default`` has its own copy.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import CONFIG_DIR
from .resolution import DEFAULT_PROFILE, ensure_profile

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
_GLOBAL_ITEMS: frozenset[str] = frozenset(
    {
        "credentials.json",  # not moved here; seeded into default lazily
        "mcp_tokens",
        "plugins",
        "plugins_state.json",
        "logs",
        "profiles",
        "active_profile",
        "memory",  # the providers dir lives under profile/memory/
    }
)


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
                item,
                dst,
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
            "profile migration: moved %d item(s), %d failure(s) to ~/.athena/profiles/%s/",
            len(moved),
            len(failed),
            DEFAULT_PROFILE,
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


# ---------------------------------------------------------------------------
# R2 stage 4 -- workspace-keyed legacy memory -> profile-keyed sub-store
# ---------------------------------------------------------------------------


def migrate_workspace_memory(
    *,
    profile: str,
    workspace: Path,
    home: Path | None = None,
    dry_run: bool = False,
) -> dict[str, list[str] | bool]:
    """Copy legacy workspace-keyed memory into the new sub-store.

    Source: ``<home>/.athena/projects/<workspace-slug>/memory/`` --
    where every previous athena release wrote memories for this
    workspace.

    Target: ``<profile_dir>/memory/legacy/<workspace-slug>/`` --
    the R2-stage-1 layout the new provider reads from.

    Behaviour:

    * If the source dir doesn't exist, the migration is a no-op and
      returns ``{"copied": [], "skipped": [], "ran": False}``.
    * If the target dir ALREADY exists (the user, or a previous run,
      already migrated this workspace), the migration is a no-op too
      -- returning the same shape. This makes the function safely
      idempotent; calling it on every session is cheap.
    * Otherwise, every regular file under the source dir is copied
      verbatim into the target dir. The ``MEMORY.md`` index comes
      along so the agent's system-prompt build sees the migrated
      entries on the next session without needing a re-index. The
      provider's SQLite mirror gets rebuilt on first
      :meth:`list_entries` via ``_reconcile_from_disk``.
    * ``dry_run=True`` reports what WOULD copy without touching disk.

    Returns ``{"copied": [<filename>, ...], "skipped": [...],
    "ran": True/False, "source": <str>, "target": <str>}``. Callers
    (typically :class:`~athena.agent.core.Agent`'s opportunistic
    ``__init__`` invocation) can log the summary.
    """
    from ..config import profile_dir as _profile_dir
    from ..memory.providers.builtin_file import BuiltinFileProvider

    slug = BuiltinFileProvider.workspace_slug(workspace)
    # ``home`` is the same override the provider uses. ``None`` means
    # "production CONFIG_DIR" (resolves to ``~/.athena/`` -- the legacy
    # ``projects/<slug>/memory/`` root sits next to ``profiles/``). A
    # non-None ``home`` (used by tests + the future operator CLI) lays
    # out ``<home>/projects/...`` and ``<home>/profiles/...`` parallel
    # so the two roots agree.
    base = home if home is not None else CONFIG_DIR
    source = base / "projects" / slug / "memory"
    # Pass ``base`` (not ``home``) to ``_profile_dir`` so target and
    # source share a single resolved root. Otherwise ``home=None`` +
    # a monkey-patched ``migration.CONFIG_DIR`` would route source to
    # the patched root but target to the original ``athena.config.
    # CONFIG_DIR`` -- they'd disagree, defeating the migration.
    target = _profile_dir(profile, home=base) / "memory" / "legacy" / slug

    if not source.exists():
        return {
            "copied": [],
            "skipped": [],
            "ran": False,
            "source": str(source),
            "target": str(target),
        }

    if target.exists():
        # Someone already migrated this workspace -- maybe a prior
        # session under the same profile + workspace, or the user
        # copied it by hand. Skip to keep the function idempotent.
        return {
            "copied": [],
            "skipped": [],
            "ran": False,
            "source": str(source),
            "target": str(target),
        }

    copied: list[str] = []
    skipped: list[str] = []
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
    for entry in sorted(source.iterdir()):
        if not entry.is_file():
            skipped.append(entry.name)
            continue
        if dry_run:
            copied.append(entry.name)
            continue
        try:
            shutil.copy2(str(entry), str(target / entry.name))
            copied.append(entry.name)
        except Exception:
            logger.exception(
                "memory migration: failed to copy %s for workspace %s",
                entry.name,
                workspace,
            )
            skipped.append(entry.name)

    logger.info(
        "memory migration: %s %d file(s) for profile=%s workspace=%s",
        "would copy" if dry_run else "copied",
        len(copied),
        profile,
        workspace,
    )
    return {
        "copied": copied,
        "skipped": skipped,
        "ran": True,
        "source": str(source),
        "target": str(target),
    }


def maybe_migrate_workspace_memory(cfg, workspace: Path) -> dict[str, list[str] | bool] | None:
    """Convenience wrapper called from :class:`~athena.agent.core.Agent`
    construction. Returns ``None`` when the flag is off (the common
    case during the dogfood window); otherwise returns the
    :func:`migrate_workspace_memory` summary."""
    if not getattr(cfg, "migrate_legacy_memory", False):
        return None
    profile = getattr(cfg, "profile", None) or "default"
    return migrate_workspace_memory(profile=profile, workspace=workspace)
