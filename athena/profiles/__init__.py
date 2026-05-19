"""Multi-profile isolation.

Each profile is its own configuration / skill set / memory / session
store / cron schedule / gateway routes. Users run ``personal`` and
``work`` side-by-side without crosstalk:

    ~/.athena/
      profiles/
        default/
          config.toml
          skills/
          memory/
          sessions/
          mcp.json
          goal.txt
          ...
        work/
          ...
      credentials.json        <-- global (user-scope, not profile)
      mcp_tokens/             <-- global (per-server)
      plugins/                <-- global
      active_profile          <-- set by `athena profile switch`

Active profile resolution: CLI ``--profile`` flag beats
``ATHENA_PROFILE`` env var beats the ``active_profile`` file beats
``cfg.profile`` (from the loaded config.toml) beats the hardcoded
``"default"``.

Migration: on first run after the multi-profile aware release, any
profile-level files at the top of ``~/.athena/`` (legacy single-
profile layout from earlier phases) move into
``profiles/default/``. Idempotent — runs once.
"""

from .manager import (
    create_profile,
    delete_profile,
    list_profiles,
    rename_profile,
    switch_profile,
)
from .resolution import (
    ACTIVE_PROFILE_FILE,
    DEFAULT_PROFILE,
    PROFILES_DIR,
    ensure_profile,
    profile_dir,
    profile_exists,
    resolve_active_profile,
)

__all__ = [
    "ACTIVE_PROFILE_FILE",
    "DEFAULT_PROFILE",
    "PROFILES_DIR",
    "create_profile",
    "delete_profile",
    "ensure_profile",
    "list_profiles",
    "profile_dir",
    "profile_exists",
    "rename_profile",
    "resolve_active_profile",
    "switch_profile",
]
