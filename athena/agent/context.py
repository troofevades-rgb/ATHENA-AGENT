"""Per-thread "currently running agent" registry.

R1 stage 3 split this out of :mod:`athena.agent.core` so the
:class:`~athena.agent.runtime.AgentRuntime` mixin can read and
swap the ContextVar without dragging in the rest of ``core`` (the
mixin lives in a sibling module ``core`` itself imports for the
inheritance hierarchy; a direct ``runtime -> core`` import would
cycle).

Callers should keep using ``athena.agent.core.get_current_agent``
or ``athena.agent.get_current_agent`` -- both re-export the
function defined here.
"""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .core import Agent


# ContextVar so a fork running on its own thread can register itself as the
# current parent for any grand-children it spawns, without clobbering the
# foreground agent on the main thread.
_current_agent: contextvars.ContextVar["Agent | None"] = contextvars.ContextVar(
    "athena_current_agent", default=None
)


def get_current_agent() -> "Agent | None":
    """Return the Agent whose run_turn is currently active on this context, or None."""
    return _current_agent.get()
