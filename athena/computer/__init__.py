"""Computer use — desktop control (T6-04).

Athena can observe the user's screen and (with explicit consent)
drive input. The permission model is the **entire** safety
boundary — there's no sandbox isolation here; computer use is
the *inverse* of T5-02's sandbox.

Build order is safety-first:

  1. Contract + classification + permission gate   (T6-04.1)
  2. Kill switch                                   (T6-04.2)
  3. Observe-only desktop backend                  (T6-04.3)
  4. Observe-only co-pilot mode + audit log        (T6-04.4)
  5. Observe-act loop + input backend (gated)      (T6-04.5)
  6. Dry-run + docs + hardened-default verify      (T6-04.6)

Nothing in this package performs an input event until the
permission gate has returned True. There is **one** call site
for ``backend.perform`` — inside the loop, after ``gate.check``.
"""

from .contract import Action, DesktopBackend, Screenshot, Tier
from .permission import PermissionGate, classify

__all__ = [
    "Action",
    "DesktopBackend",
    "PermissionGate",
    "Screenshot",
    "Tier",
    "classify",
]
