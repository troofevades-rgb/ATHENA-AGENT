"""Gateway credential resolver — cleartext-in-config → path-on-disk.

Every gateway platform that needs a long-lived secret (Discord
bot_token, Slack bot_token + app_token, Telegram bot_token,
Signal password, iMessage password, Matrix access_token) used
to read it as a cleartext string from ``cfg.gateway.platforms.<name>``.

That's the same footgun the X bearer-token migration solved:
a token in ``config.toml`` shows up in dotfile backups, in
``cat ~/.athena/config.toml`` over a shared screen, in process
arguments if anyone passes ``--config`` with that file, and
in any tool that auto-loads dotfiles.

This module's :func:`resolve_credential` lets a platform
declare a secret by EITHER:

  - ``<key>_path`` — path to a 0o600 file containing just the
    secret (no quoting, no JSON wrapping, trailing whitespace
    stripped). The preferred shape going forward.

  - ``<key>``       — cleartext in the config file. Still
    works but logs a one-shot WARNING per
    ``(platform, key)`` so the operator sees the rotation
    nudge without being spammed every time the gateway
    restarts.

A platform that requires the secret and gets neither raises
``ValueError`` with a message naming BOTH possible config
shapes so the operator knows what to fix.

The resolver never logs the secret material. The fallback-
warning message names the key (e.g. ``"discord.bot_token"``)
and the path it'd live at if migrated — not the value.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Per-process memo: each (platform, key) pair warns at most once
# even when the gateway restarts the adapter mid-session
# (reconnect after a transient SDK disconnect, for example).
# Without the memo a flapping connection would print the same
# rotation nudge dozens of times per minute.
_warned: set[tuple[str, str]] = set()
_warned_lock = threading.Lock()


def resolve_credential(
    settings: dict[str, Any],
    key: str,
    *,
    platform: str,
    required: bool = True,
) -> str | None:
    """Resolve a long-lived gateway secret.

    Lookup order:

      1. ``settings[f"{key}_path"]`` — read the file at that
         path. Returns the stripped contents (None if the file
         exists but is empty / whitespace-only, treated like
         "missing").
      2. ``settings[key]`` — the legacy cleartext path. Logs a
         one-shot deprecation warning per ``(platform, key)``.
      3. Neither: ``None`` (when ``required=False``) or
         ``ValueError`` (when ``required=True``).

    Never raises into a log handler — file-read errors return
    None at the *_path step and the cleartext fallback fires.

    Never logs the secret. The deprecation message names the
    config key and the path it'd land at if migrated, not the
    value.
    """
    path_value = settings.get(f"{key}_path")
    if path_value:
        p = Path(str(path_value)).expanduser()
        try:
            raw = p.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning(
                "gateway %s.%s_path %s unreadable: %s — "
                "falling back to cleartext if present",
                platform, key, p, e,
            )
        else:
            tok = raw.strip()
            if tok:
                logger.debug(
                    "gateway %s.%s loaded from %s (len=%d)",
                    platform, key, p, len(tok),
                )
                return tok
            logger.warning(
                "gateway %s.%s_path %s is empty — "
                "falling back to cleartext if present",
                platform, key, p,
            )

    cleartext = settings.get(key)
    if cleartext:
        _warn_once(platform, key)
        return str(cleartext)

    if required:
        raise ValueError(
            f"gateway platform {platform!r} requires {key!r}: "
            f"set either {key}_path (a 0o600 file with the secret) "
            f"or {key} (cleartext, deprecated)"
        )
    return None


def _warn_once(platform: str, key: str) -> None:
    """Log a one-shot rotation nudge for a (platform, key)
    pair. Subsequent calls are silent for that pair.

    The message names the migration path explicitly so an
    operator reading the log knows exactly what to change.
    """
    pair = (platform, key)
    with _warned_lock:
        if pair in _warned:
            return
        _warned.add(pair)
    logger.warning(
        "gateway %s.%s is configured as cleartext in config.toml; "
        "for safety move it to %s_path pointing at a 0o600 file "
        "(see docs/reference/gateway-credentials.md for the "
        "migration recipe)",
        platform, key, key,
    )


def _reset_warning_memo_for_tests() -> None:
    """Test-only — clear the one-shot warning memo so a fresh
    test gets a fresh deprecation-warning fire."""
    with _warned_lock:
        _warned.clear()
