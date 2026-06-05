"""TTS backend registrations.

Importing this package runs each backend module for its
``@register_provider`` side effect, so the resolver sees every in-tree
text-to-speech backend. Heavy / optional engine imports (piper) live
*inside* the backend methods, so importing the modules here is always
safe — a missing engine surfaces later as ``is_available() == False``,
never an import error.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Each import is guarded so one broken backend can't suppress the others.
try:
    from . import stub as _stub  # noqa: F401
except Exception as e:  # noqa: BLE001
    logger.warning("tts: stub backend not loaded: %s", e)

try:
    from . import piper_local as _piper  # noqa: F401
except Exception as e:  # noqa: BLE001
    logger.warning("tts: piper_local backend not loaded: %s", e)
