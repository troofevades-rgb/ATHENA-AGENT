"""Gateway daemon — exposes the agent to chat platforms.

A single async daemon hosts one or more :class:`GatewayAdapter`s (one
per platform: Telegram, Slack, Discord). Inbound platform messages
route to per-(platform, chat, user) sessions; the agent runs inside the
asyncio event loop via :func:`asyncio.to_thread`.

Reliability primitives that the base adapter bakes in:

- **Stale-lock self-heal** (:mod:`.healing`) — a per-session
  ``asyncio.Lock`` that has been held longer than the heartbeat
  threshold gets force-released so a crashed task can't wedge a session.
- **Heartbeat** (:mod:`.heartbeat`) — long tool calls bump a per-session
  timestamp so the adapter can keep a typing indicator alive.
- **Approval routing** (added in Prompt 10.3) — dangerous tools surface
  a platform-specific confirm UI; the user's reply unblocks the tool.
- **Cross-platform continuity** (added in Prompt 10.3) — opt-in linking
  so the same user on Slack and Telegram shares one session.
"""
