"""Resolve a usable :class:`SpeechSynthBackend` from config.

Mirrors the capability-resolution pattern used for STT
(``audio.tools._resolve_backend``) and video
(``videogen.resolve_backend``): backends register as providers declaring
the ``text_to_speech`` capability, and selection is config-pinned first,
broker-style (local-first) otherwise.

Two robustness rules the single-pick broker doesn't give on its own, and
that the voice design needs:

  - **availability fallback.** A candidate that declares the capability
    but whose engine isn't installed / configured (``is_available()`` ==
    False) is skipped, and the next candidate is tried — rather than
    returning a dead backend.
  - **no silent stubs.** The deterministic ``tts_stub`` (silent WAVs) is
    excluded from auto-selection; it is reachable only by an explicit
    ``cfg.tts_backend = "tts_stub"`` pin. Silence masquerading as speech
    is worse than an honest "TTS unavailable".

Returns ``None`` when nothing is available — the caller degrades the turn
gracefully (the voice session falls back to a text reply).
"""

from __future__ import annotations

import logging
from typing import Any

from ...providers import get_provider_class, list_providers
from ...providers.base import Provider
from .base import SpeechSynthBackend

logger = logging.getLogger(__name__)


def _construct(cls: type[Provider], cfg: Any) -> SpeechSynthBackend | None:
    """Instantiate a backend class, passing ``cfg`` so it can read voice
    settings. Returns None (logged) if construction fails."""
    try:
        inst = cls(cfg=cfg)
    except Exception as e:  # noqa: BLE001
        logger.warning("tts: backend %r failed to construct: %s", cls.__name__, e)
        return None
    if not hasattr(inst, "synthesize"):
        logger.warning("tts: backend %r does not implement synthesize()", cls.__name__)
        return None
    return inst  # type: ignore[return-value]


def _tts_classes() -> list[type[Provider]]:
    """Every registered provider that declares ``text_to_speech``, ordered
    local-first with ``test_only`` backends last."""
    out: list[type[Provider]] = []
    for name in list_providers():
        cls = get_provider_class(name)
        try:
            caps = cls.static_capabilities()
        except Exception:  # noqa: BLE001
            continue
        if caps.supports("text_to_speech"):
            out.append(cls)
    out.sort(
        key=lambda c: (
            bool(getattr(c, "test_only", False)),
            not c.static_capabilities().is_local,
        )
    )
    return out


def resolve_tts_backend(cfg: Any) -> SpeechSynthBackend | None:
    """Return a ready, available TTS backend, or ``None``.

    1. ``cfg.tts_backend`` pin wins (any registered backend, including
       ``tts_stub``) when it declares the capability and is available.
    2. Otherwise: the first available, non-``test_only`` backend,
       local-first.
    """
    # Registration side effect — make sure the in-tree backends exist.
    from . import backends  # noqa: F401

    pin = (getattr(cfg, "tts_backend", "") or "").strip()
    if pin:
        try:
            cls = get_provider_class(pin)
        except KeyError:
            logger.warning(
                "tts: cfg.tts_backend=%r is not a registered provider; using broker", pin
            )
            cls = None
        if cls is not None:
            if not cls.static_capabilities().supports("text_to_speech"):
                logger.warning(
                    "tts: cfg.tts_backend=%r does not declare text_to_speech; using broker", pin
                )
            else:
                inst = _construct(cls, cfg)
                if inst is not None and inst.is_available():
                    return inst
                logger.warning("tts: pinned backend %r is unavailable; using broker", pin)

    for cls in _tts_classes():
        if getattr(cls, "test_only", False):
            continue
        inst = _construct(cls, cfg)
        if inst is not None and inst.is_available():
            logger.info("tts: resolved backend %s", cls.name)
            return inst

    logger.info("tts: no available text_to_speech backend")
    return None
