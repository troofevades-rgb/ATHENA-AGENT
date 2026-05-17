"""Agent Client Protocol adapter.

The Agent Client Protocol (ACP) is a JSON-RPC protocol for embedding
agents inside IDEs. Zed supports it natively; VS Code and JetBrains
have community adapters. Implementing ACP gives athena IDE
integration without per-IDE extensions.

The server speaks JSON-RPC 2.0 over stdio: stdin is requests
inbound, stdout is responses and notifications outbound, stderr is
diagnostic logs. One ACP subprocess handles one IDE client; the IDE
manages session lifecycle (``session/new``, ``session/end``).

Modules:

- :mod:`.server` — JSON-RPC framing, method/notification dispatch,
  client-bound requests with pending-future tracking.
- :mod:`.capabilities` — what we advertise during ``initialize``.
- :mod:`.streaming` — wraps server.send_notification for the streaming
  primitives the IDE expects (text_delta, tool_call_start/result,
  permission_request).
- :mod:`.methods` — implements every method the IDE calls.
- :mod:`.slash_commands` — ``/steer``, ``/queue``, ``/goal`` handlers.
"""
