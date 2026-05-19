"""HTTP webhook listener.

External services (GitHub, Linear, monitoring tools, custom apps)
POST events to ``http://<host>:<port>/webhook/<id>``. Each webhook
is bound to a skill (or a prompt template) and optionally delivers
its output to a chat via the gateway. Cron's incoming-event cousin:
cron fires on time; webhooks fire on external events.

Modules:

- :mod:`.subscription` — :class:`WebhookSubscription` dataclass +
  :class:`WebhookStore` (SQLite at ``<profile>/webhooks.db``).
- :mod:`.auth` — constant-time HMAC-SHA256 and Bearer verification.
- :mod:`.idempotency` — TTL-scoped duplicate-key cache so a
  retrying webhook source doesn't fire the agent twice.
- :mod:`.server` — the aiohttp listener (Phase 15.2).
- :mod:`.delivery` — dispatch a fired webhook to the agent + route
  the response (Phase 15.3).
"""

from .auth import verify_bearer, verify_hmac_sha256
from .idempotency import IdempotencyCache
from .subscription import WebhookStore, WebhookSubscription

__all__ = [
    "IdempotencyCache",
    "WebhookStore",
    "WebhookSubscription",
    "verify_bearer",
    "verify_hmac_sha256",
]
