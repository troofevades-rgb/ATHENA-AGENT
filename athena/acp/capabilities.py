"""Capability advertisement for the ``initialize`` handshake.

The IDE asks what we support up front; we hand back the
:data:`CAPABILITIES` table plus our server identity and the protocol
version we speak. The values are conservative — we advertise what's
actually wired through to the rest of athena, not aspirational
features.

Don't add a key here without a working implementation. The IDE will
take us at our word and call us for any capability we claim — an
unhandled call produces a noisy error in the user's editor.
"""
from __future__ import annotations


PROTOCOL_VERSION = "1.0"


SERVER_INFO = {
    "name": "athena",
    "version": "0.2.0",
}


CAPABILITIES = {
    # Stream content_block_delta notifications as the agent produces
    # tokens. Required for a "typing" effect in Zed and similar IDEs.
    "streaming": True,
    # Surface tool calls via content_block_start / tool_result
    # notifications.
    "tools": True,
    # Send permission_request to the client for dangerous tools;
    # await user decision.
    "approvals": True,
    # File attachments come in via session/send_message's params and
    # appear on the agent's MessageEvent as Path entries.
    "file_attachments": True,
    # /steer, /queue, /goal via session/slash_command.
    "slash_commands": True,
    # models/list returns every provider:model name the resolver
    # would accept.
    "models_listing": True,
    # session/new + session/end IDE-driven lifecycle.
    "session_lifecycle": True,
}
