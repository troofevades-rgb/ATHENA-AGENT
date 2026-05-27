"""dotenv loader for athena credentials.

A single ``~/.athena/.env`` file replaces the per-token ``*_path``
config knobs as the primary credential surface. The legacy paths
still work — :func:`get_credential` falls back to them when a key
isn't in ``.env``.

Format::

    # ~/.athena/.env
    ATHENA_XAI_API_KEY=xai-1234...
    ATHENA_RUNWAY_API_KEY="rw-..."
    ATHENA_X_BEARER_TOKEN='AAAA...'

Rules:

  - One ``KEY=value`` per line.
  - ``#`` starts a comment to end-of-line.
  - Surrounding single or double quotes on the value are stripped.
  - Whitespace around the ``=`` is allowed.
  - Lines without ``=`` are silently skipped.
  - Later lines for the same key override earlier ones.

The file is read on demand and cached for the process lifetime.
Call :func:`reset_cache` from a test or after rewriting the file.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)


_DOTENV_PATH: Path = Path.home() / ".athena" / ".env"

# Process-lifetime cache. Avoid re-parsing on every credential lookup —
# the file rarely changes mid-session.
_cache: dict[str, str] | None = None


def _path() -> Path:
    """Return the dotenv path. Indirection so tests can monkeypatch."""
    return _DOTENV_PATH


def reset_cache() -> None:
    """Drop the parsed cache. Call after rewriting the .env file or
    in tests."""
    global _cache
    _cache = None


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        # Strip inline comments (only at line start to avoid eating
        # # characters that legitimately appear in token values).
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        # Strip a single layer of matching quotes.
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key:
            out[key] = val
    return out


def load_dotenv() -> dict[str, str]:
    """Parse ``~/.athena/.env`` and return a dict. Cached for the
    process lifetime. Empty dict when the file is absent or unreadable.

    A warning is logged when the file exists with permissions wider
    than 0o600 — credentials in a world-readable file is a real
    concern even though we still load them.
    """
    global _cache
    if _cache is not None:
        return _cache
    path = _path()
    if not path.exists():
        _cache = {}
        return _cache
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("could not read %s: %s", path, e)
        _cache = {}
        return _cache
    # Permission check — best-effort on POSIX; Windows ACLs are a
    # different beast so the check is informational only.
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            logger.warning(
                "%s is mode %o; recommend chmod 0o600 — credentials "
                "in this file are readable by other users",
                path, mode,
            )
    except OSError:
        pass
    _cache = _parse(text)
    return _cache


def get_credential(
    key: str,
    *,
    fallback_path: str | None = None,
    default: str | None = None,
) -> str | None:
    """Resolve a credential by name. Lookup order:

    1. ``~/.athena/.env`` (cached)
    2. Process environment (``os.environ``)
    3. ``fallback_path`` — read contents of the file if provided + present.
       Strips trailing whitespace.
    4. ``default``

    Returns ``None`` when no source has a value. Never raises — a
    missing credential is the caller's concern, not the resolver's.
    """
    env_vars = load_dotenv()
    if key in env_vars and env_vars[key]:
        return env_vars[key]
    val = os.environ.get(key)
    if val:
        return val
    if fallback_path:
        try:
            p = Path(fallback_path).expanduser()
            if p.is_file():
                return p.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return default
