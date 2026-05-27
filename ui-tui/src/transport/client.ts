/**
 * JSON-RPC 2.0 client used by the Ink TUI to talk to the Python
 * ``athena.tui_gateway`` over a dedicated socket.
 *
 * Transport selection (TUI sprint step 3):
 *   - If ``ATHENA_TUI_SOCK`` is set, connect to that Unix domain
 *     socket path. This is the default on POSIX.
 *   - Otherwise, if ``ATHENA_TUI_PORT`` is set, connect to TCP
 *     loopback on 127.0.0.1:<port>. Windows default and POSIX
 *     fallback when ``ATHENA_TUI_TRANSPORT=tcp`` on the Python side.
 *
 * Connection lifecycle (TUI sprint step 4a):
 *   - Gateway sends a HelloEvent immediately after accept.
 *   - We validate ``protocol_version`` and reply with a
 *     HelloCommand carrying our own version + ``last_seq``.
 *   - Gateway then emits a PingEvent every ~5s while alive; we
 *     reply with a PongCommand. Server declares us dead after
 *     three missed pongs and emits ProtocolErrorEvent before
 *     closing — we surface that through ``onProtocolError``.
 *   - Every gateway event carries a monotonic ``seq`` field on
 *     the envelope; we track the last seen seq for future
 *     reconnect-with-replay support (step 4b).
 *
 * Why a socket and not stdio: stdin/stdout of the spawned process
 * are needed for normal TTY interaction (keyboard input, UI
 * render). Carrying the protocol on a separate channel removes
 * that conflict and is also what enables the future web dashboard
 * to subscribe to the same stream.
 *
 * Wire format (line-delimited frames, UTF-8):
 *   {"jsonrpc":"2.0","method":"<event-type>","params":{...},"seq":N}    gateway → tui
 *   {"jsonrpc":"2.0","method":"<command>","params":{...}}               tui → gateway
 */

import { Socket, connect } from "node:net";

import type {
  Command,
  Event,
  HelloEvent,
  ProtocolErrorEvent,
} from "./protocol.js";

export type EventHandler = (event: Event) => void;
export type ProtocolErrorHandler = (event: ProtocolErrorEvent) => void;

export interface GatewayClient {
  /** Subscribe to gateway events. Returns an unsubscribe fn. */
  onEvent(handler: EventHandler): () => void;
  /** Subscribe to fatal protocol errors (version mismatch, dead
   * heartbeat, malformed hello). Emitted at most once per session
   * just before the socket closes. */
  onProtocolError(handler: ProtocolErrorHandler): () => void;
  /** Send a command back to the gateway. Fire-and-forget. */
  sendCommand(cmd: Command): void;
  /** Highest seq we've seen on the gateway's events. Used by the
   * future reconnect path to request replay. */
  getLastSeq(): number;
  /** Server's hello payload, populated after handshake completes.
   * Null until the first hello arrives. */
  getServerHello(): HelloEvent | null;
  /** Stop reading and release subscribers. */
  close(): void;
}

interface ResolvedTransport {
  kind: "uds" | "tcp";
  options: { path: string } | { host: string; port: number };
}

function resolveTransport(): ResolvedTransport {
  const sockPath = process.env["ATHENA_TUI_SOCK"];
  if (sockPath) {
    return { kind: "uds", options: { path: sockPath } };
  }
  const portRaw = process.env["ATHENA_TUI_PORT"];
  if (portRaw) {
    const port = Number.parseInt(portRaw, 10);
    if (!Number.isInteger(port) || port <= 0) {
      throw new Error(`ATHENA_TUI_PORT is not a valid port: ${portRaw}`);
    }
    return { kind: "tcp", options: { host: "127.0.0.1", port } };
  }
  throw new Error(
    "neither ATHENA_TUI_SOCK nor ATHENA_TUI_PORT is set — " +
      "this binary must be launched by athena's tui_gateway",
  );
}

/** Protocol version this build of the TUI speaks. Must match the
 * Python side's schema/v1/protocol.json `protocol_version`. */
const PROTOCOL_VERSION = 2;

/** Client capabilities advertised in the hello reply. */
const CLIENT_CAPABILITIES: readonly string[] = ["heartbeats", "seq"];

/**
 * Connect to the gateway. Picks UDS or TCP from env, performs the
 * hello handshake, handles ping/pong and seq tracking. Throws if
 * neither transport env var is set.
 */
export function connectGateway(): GatewayClient {
  const transport = resolveTransport();

  const handlers = new Set<EventHandler>();
  const protocolErrorHandlers = new Set<ProtocolErrorHandler>();
  let buffer = "";
  let closed = false;
  let helloSent = false;
  let serverHello: HelloEvent | null = null;
  let lastSeq = 0;

  const socket: Socket = connect(transport.options);

  if (transport.kind === "tcp") {
    socket.setNoDelay(true);
  }

  function writeFrame(frame: object): void {
    try {
      socket.write(JSON.stringify(frame) + "\n");
    } catch {
      // Socket closed — the close handler will fire shortly.
    }
  }

  function sendHello(): void {
    if (helloSent) return;
    helloSent = true;
    writeFrame({
      jsonrpc: "2.0",
      method: "hello",
      params: {
        protocol_version: PROTOCOL_VERSION,
        client_version: "tui-bundle",
        capabilities: CLIENT_CAPABILITIES,
        last_seq: 0,
      },
    });
  }

  function sendPong(): void {
    writeFrame({
      jsonrpc: "2.0",
      method: "pong",
      params: {},
    });
  }

  socket.on("data", (chunk: Buffer) => {
    if (closed) return;
    buffer += chunk.toString("utf-8");
    let nl = buffer.indexOf("\n");
    while (nl !== -1) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line) {
        dispatch(line);
      }
      nl = buffer.indexOf("\n");
    }
  });

  socket.on("close", () => {
    if (closed) return;
    for (const h of handlers) {
      h({ type: "exit", reason: "gateway socket closed" });
    }
  });

  socket.on("error", () => {
    if (closed) return;
    for (const h of handlers) {
      h({ type: "exit", reason: "gateway socket error" });
    }
  });

  function dispatch(line: string): void {
    let frame: unknown;
    try {
      frame = JSON.parse(line);
    } catch {
      return;
    }
    if (typeof frame !== "object" || frame === null) return;
    const fr = frame as {
      method?: unknown;
      params?: unknown;
      seq?: unknown;
    };
    if (typeof fr.method !== "string") return;
    if (typeof fr.seq === "number" && Number.isFinite(fr.seq)) {
      // Track the highest seq we've seen on the server side.
      // Server seq is monotonically increasing within one session;
      // we keep the max so out-of-order frames (shouldn't happen
      // on a single TCP/UDS socket, but defensive) don't move it
      // backwards.
      if (fr.seq > lastSeq) {
        lastSeq = fr.seq;
      }
    }
    const params =
      fr.params && typeof fr.params === "object" && !Array.isArray(fr.params)
        ? (fr.params as Record<string, unknown>)
        : {};
    const event = { ...params, type: fr.method } as Event;

    // ---- transport-internal frames: don't surface to handlers ----
    if (event.type === "hello") {
      const he = event as HelloEvent;
      serverHello = he;
      if (he.protocol_version !== PROTOCOL_VERSION) {
        // We will send our hello anyway — server expects it. Server
        // will detect the mismatch and emit ProtocolErrorEvent.
        // No need to short-circuit here.
      }
      sendHello();
      return;
    }
    if (event.type === "ping") {
      sendPong();
      return;
    }
    if (event.type === "protocol.error") {
      const pe = event as ProtocolErrorEvent;
      for (const h of protocolErrorHandlers) {
        h(pe);
      }
      // Also let normal exit flow happen — server will close shortly.
      return;
    }

    // ---- user-facing events ----
    for (const h of handlers) {
      h(event);
    }
  }

  function sendCommand(cmd: Command): void {
    if (closed) return;
    const { type, ...params } = cmd;
    writeFrame({
      jsonrpc: "2.0",
      method: type,
      params,
    });
  }

  function close(): void {
    if (closed) return;
    closed = true;
    handlers.clear();
    protocolErrorHandlers.clear();
    try {
      socket.end();
    } catch {
      // best-effort
    }
  }

  function onEvent(handler: EventHandler): () => void {
    handlers.add(handler);
    return () => handlers.delete(handler);
  }

  function onProtocolError(handler: ProtocolErrorHandler): () => void {
    protocolErrorHandlers.add(handler);
    return () => protocolErrorHandlers.delete(handler);
  }

  function getLastSeq(): number {
    return lastSeq;
  }

  function getServerHello(): HelloEvent | null {
    return serverHello;
  }

  return {
    onEvent,
    onProtocolError,
    sendCommand,
    getLastSeq,
    getServerHello,
    close,
  };
}
