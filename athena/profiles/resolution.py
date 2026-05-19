"""Active profile resolution + per-profile bootstrap.

The single source of truth for "which profile am I running as right
now". Five-level precedence, highest first:

1. CLI flag ``--profile <name>``
2. Env var ``ATHENA_PROFILE`` (legacy ``OCODE_PROFILE`` honored too)
3. The contents of ``~/.athena/active_profile`` (set by
   ``athena profile switch``)
4. The ``profile`` field of the loaded ``config.toml``
5. Hardcoded ``"default"``

(4) is handled at the :mod:`athena.config` layer; (1)-(3) and (5)
live here because they're orthogonal to the typed ``Config``.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Final

from ..config import CONFIG_DIR

logger = logging.getLogger(__name__)


DEFAULT_PROFILE: Final = "default"
PROFILES_DIR: Final = CONFIG_DIR / "profiles"
ACTIVE_PROFILE_FILE: Final = CONFIG_DIR / "active_profile"


# Profile names: lowercase alphanumerics + ``_`` + ``-``, max 64 chars,
# must start with an alphanumeric. Keeps filesystem-unfriendly chars
# and shell metacharacters out without limiting expressiveness.
_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def is_valid_profile_name(name: str) -> bool:
    """True iff ``name`` is safe to use as a profile directory name.

    Strict: lowercase only, no spaces / dots / slashes / shell-
    special chars. The ``_NAME_PATTERN`` regex documents the exact
    grammar.
    """
    if not isinstance(name, str):
        return False
    return bool(_NAME_PATTERN.match(name))


def profile_dir(name: str) -> Path:
    """Return the on-disk root for ``name``.

    Does NOT create the directory — caller asks for it because they
    want the path, not necessarily a side effect. Use
    :func:`ensure_profile` when you want bootstrap behavior.
    """
    if not is_valid_profile_name(name):
        raise ValueError(
            f"invalid profile name: {name!r} (lowercase alphanumerics + _ - only, max 64 chars)"
        )
    return PROFILES_DIR / name


def profile_exists(name: str) -> bool:
    """Cheap presence check — no validation; returns False on invalid
    names (rather than raising) because callers often want a soft
    test."""
    if not is_valid_profile_name(name):
        return False
    return profile_dir(name).is_dir()


def ensure_profile(name: str) -> Path:
    """Create the profile directory with bootstrap subdirs if needed.

    Idempotent. Returns the profile root. Does NOT seed a config.toml
    — that's the manager's job for ``create_profile``; ensure is the
    low-level "make sure the layout exists for the active profile"
    helper.
    """
    root = profile_dir(name)
    root.mkdir(parents=True, exist_ok=True)
    for subdir in ("skills", "memory", "sessions"):
        (root / subdir).mkdir(exist_ok=True)
    return root


def resolve_active_profile(
    cli_arg: str | None = None,
    *,
    config_default: str | None = None,
) -> str:
    """Walk the precedence chain and return the active profile name.

    ``cli_arg`` is what the user typed at ``--profile``;
    ``config_default`` is the ``profile`` field from the loaded
    Config (passed through so we don't double-load it).

    Any invalid name at any step degrades to the next step rather
    than raising — the user shouldn't get a stack trace from typing
    ``athena --profile 'has spaces'``; instead they'll silently land
    on the next-best source. A debug log explains what happened.
    """
    candidates = (
        ("cli", cli_arg),
        ("env", os.environ.get("ATHENA_PROFILE") or os.environ.get("OCODE_PROFILE")),
        ("active_file", _read_active_file()),
        ("config", config_default),
    )
    for source, value in candidates:
        if not value:
            continue
        if not is_valid_profile_name(value):
            logger.warning(
                "profile from %s is invalid (%r); falling through",
                source,
                value,
            )
            continue
        return value
    return DEFAULT_PROFILE


def _read_active_file() -> str | None:
    """Read ``~/.athena/active_profile`` (set by
    ``athena profile switch``). Tolerant of missing file, empty
    contents, trailing whitespace."""
    if not ACTIVE_PROFILE_FILE.exists():
        return None
    try:
        value = ACTIVE_PROFILE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def set_active_profile_file(name: str) -> None:
    """Persist ``name`` to ``~/.athena/active_profile``. Atomic via
    tempfile + os.replace so a crash mid-write doesn't truncate the
    file."""
    if not is_valid_profile_name(name):
        raise ValueError(f"invalid profile name: {name!r}")
    ACTIVE_PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVE_PROFILE_FILE.with_suffix(".tmp")
    tmp.write_text(name, encoding="utf-8")
    os.replace(tmp, ACTIVE_PROFILE_FILE)


def clear_active_profile_file() -> None:
    """Delete ``~/.athena/active_profile``. Subsequent resolution
    will fall through to env / config / default."""
    if ACTIVE_PROFILE_FILE.exists():
        try:
            ACTIVE_PROFILE_FILE.unlink()
        except OSError:
            logger.warning(
                "failed to remove active_profile file",
                exc_info=True,
            )
