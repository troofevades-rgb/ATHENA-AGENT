"""Capability-manifest-driven media-backend registry (T5-05.1).

For a named capability (``"vision"``, ``"embeddings"``, etc.),
:meth:`MediaRegistry.backend_for` returns the provider class
that should service the request — choosing among providers whose
T5-01 capability manifest declares the capability.

Selection policy:

1. Filter the provider registry to those whose class-level
   manifest declares the requested capability.
2. If ``cfg.media_backend_prefer == "local"`` (default), pick
   the first one whose manifest says ``is_local=True``.
3. Otherwise fall back to the alphabetically-first declared
   provider — deterministic so the same install routes the
   same way across invocations.

Returning ``None`` is the explicit "no backend on this host can
do that" signal — callers (e.g. the differentiated MCP surface)
check for None and either skip advertising the capability or
return a clear error.

Every routing decision is logged at INFO so a misroute is
visible in the journal without grep-spelunking through provider
code.

Note on the provider class vs. instance distinction: this
registry returns the provider *class*, not an instantiated
client. Class-level lookup is cheap, stateless, and avoids the
credential dance — the caller instantiates only when it
actually needs to make a request. The caller can also use
:func:`athena.providers.runtime_resolver.available_providers_with_capability`
to additionally gate on credential availability before deciding
the tool is usable.
"""

from __future__ import annotations

import logging
from typing import Any

from ..providers import _REGISTRY, Provider

logger = logging.getLogger(__name__)


class MediaRegistry:
    """Resolves media operations to backends via the T5-01 manifest."""

    def __init__(self, *, cfg: Any):
        self.cfg = cfg

    def backend_for(self, capability: str) -> type[Provider] | None:
        """Return the provider class that should service
        ``capability``, or None when no registered provider
        declares it.

        Selection: local-first when ``cfg.media_backend_prefer ==
        "local"``; alphabetical otherwise. Class-level only —
        does not check credentials. For credential-aware
        resolution, layer
        :func:`athena.providers.runtime_resolver.available_providers_with_capability`
        on top of this call.
        """
        candidates = sorted(
            (name, cls)
            for name, cls in _REGISTRY.items()
            if cls.static_capabilities().supports(capability)
        )
        if not candidates:
            logger.info("media:%s → no backend declares this capability", capability)
            return None

        prefer = getattr(self.cfg, "media_backend_prefer", "local")
        if prefer == "local":
            for name, cls in candidates:
                if cls.static_capabilities().is_local:
                    logger.info("media:%s → %s (local preferred)", capability, name)
                    return cls

        name, cls = candidates[0]
        logger.info("media:%s → %s", capability, name)
        return cls

    def candidates(self, capability: str) -> list[str]:
        """All registered provider names whose manifest declares
        ``capability``. Useful for the differentiated MCP surface
        to show "this capability is available via X, Y, Z" in
        admin tooling. Sorted for stable output."""
        return sorted(
            name
            for name, cls in _REGISTRY.items()
            if cls.static_capabilities().supports(capability)
        )

    def can(self, capability: str) -> bool:
        """``True`` iff at least one registered provider declares
        ``capability``. The differentiated MCP surface checks
        this before advertising a capability-dependent tool —
        no provider declares it → tool isn't advertised."""
        return any(
            cls.static_capabilities().supports(capability)
            for cls in _REGISTRY.values()
        )
