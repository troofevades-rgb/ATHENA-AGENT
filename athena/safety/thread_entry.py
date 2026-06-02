"""Standard thread-entry setup for non-foreground tool-loop workers.

Any worker that runs an :class:`~athena.agent.Agent` off the main
thread — a fork, a cron *agent* job, webhook delivery, an eval task
runner — MUST install three things, and must do so INSIDE the worker
thread's target: ``threading.Thread`` (and ``asyncio.to_thread``) do
NOT propagate ContextVars to the worker, so setting them on the
spawning thread is a silent no-op.

The three:

  * **write-origin** (provenance) — so the worker's writes are
    attributed to its subsystem (``background_review`` / ``cron`` /
    ``system`` / …). Without it every mutation looks like
    ``foreground`` and the curator refuses to prune it.
  * **AUTO_DENY approval callback** — so a confirmation-required tool
    (Bash outside the allowlist, etc.) auto-denies instead of blocking
    forever on a stdin the daemon doesn't own (the classic deadlock).
  * **a fresh approval-grants scope** — so session grants ("always
    allow Bash") can't leak in or out across the thread boundary
    (the grant cache otherwise shares a mutable default).

These were hand-rolled in four places and had already drifted (cron
and webhooks set write-origin but no grant scope; the eval runner set
neither). Bundling them here means a new non-foreground subsystem
can't install two of the three and silently deadlock or mislabel its
writes.

NOTE: this is for AUTO_DENY workers only. The gateway and ACP install
their OWN interactive approval callbacks (they can prompt a human over
the wire) — they deliberately do not use this helper.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from ..provenance import reset_current_write_origin, set_current_write_origin
from .approval_callback import AUTO_DENY, reset_approval_callback, set_approval_callback
from .approval_guard import reset_approvals, scope_fresh_approvals


@contextlib.contextmanager
def non_foreground_thread(*, origin: str) -> Iterator[None]:
    """Install write-origin + AUTO_DENY + a fresh approval-grants scope
    for the duration of the block. Enter it INSIDE the worker thread.

    ``origin`` is a provenance constant — ``provenance.SYSTEM``,
    ``CRON``, ``BACKGROUND_REVIEW``, ``CURATOR``, etc.
    """
    origin_token = set_current_write_origin(origin)
    approval_token = set_approval_callback(AUTO_DENY)
    grants_token = scope_fresh_approvals()
    try:
        yield
    finally:
        reset_approvals(grants_token)
        reset_approval_callback(approval_token)
        reset_current_write_origin(origin_token)
