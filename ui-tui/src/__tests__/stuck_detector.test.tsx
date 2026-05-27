/**
 * Stuck-detector state transitions.
 *
 * The reducer-side contract:
 *   - USER_INPUT_SENT sets _pendingUserInputSince and _lastProgressMs
 *   - Progress events (stream/tool/message) bump _lastProgressMs and
 *     CLEAR _pendingUserInputSince
 *   - Status heartbeats do NOT bump _lastProgressMs (otherwise a slow
 *     model with active heartbeats would never look stuck)
 */

import { describe, expect, test } from "bun:test";

import { reducer } from "../state/reducer.js";
import { initialTuiState } from "../state/types.js";
import type {
  MessageAppendEvent, StatusUpdateEvent, StreamDeltaEvent,
  StreamEndEvent, StreamStartEvent, ToolCompleteEvent, ToolStartEvent,
} from "../transport/protocol.js";


describe("stuck detector — state transitions", () => {
  test("USER_INPUT_SENT sets _pendingUserInputSince and _lastProgressMs", () => {
    const before = performance.now();
    const next = reducer(initialTuiState, { type: "USER_INPUT_SENT" });
    expect(next._pendingUserInputSince).not.toBeNull();
    expect(next._pendingUserInputSince!).toBeGreaterThanOrEqual(before);
    expect(next._lastProgressMs).toBeGreaterThanOrEqual(before);
  });

  test("stream.start bumps progress AND clears _pendingUserInputSince", () => {
    const s1 = reducer(initialTuiState, { type: "USER_INPUT_SENT" });
    expect(s1._pendingUserInputSince).not.toBeNull();

    const evt: StreamStartEvent = { type: "stream.start", stream_id: "s1" };
    const s2 = reducer(s1, { type: "EVENT", event: evt });
    expect(s2._pendingUserInputSince).toBeNull();
    expect(s2._lastProgressMs).toBeGreaterThanOrEqual(s1._lastProgressMs);
    expect(s2.streamId).toBe("s1");
  });

  test("stream.delta bumps progress on each delta", async () => {
    const s1 = reducer(initialTuiState, {
      type: "EVENT",
      event: { type: "stream.start", stream_id: "x" } as StreamStartEvent,
    });
    const t1 = s1._lastProgressMs;
    // Yield a microtask so performance.now() ticks past t1
    await new Promise((r) => setTimeout(r, 2));
    const evt: StreamDeltaEvent = {
      type: "stream.delta", stream_id: "x", text: "hello",
    };
    const s2 = reducer(s1, { type: "EVENT", event: evt });
    expect(s2._lastProgressMs).toBeGreaterThan(t1);
  });

  test("stream.end bumps progress and clears streamId", () => {
    const s1 = reducer(initialTuiState, {
      type: "EVENT",
      event: { type: "stream.start", stream_id: "x" } as StreamStartEvent,
    });
    const evt: StreamEndEvent = { type: "stream.end", stream_id: "x" };
    const s2 = reducer(s1, { type: "EVENT", event: evt });
    expect(s2.streamId).toBeNull();
    expect(s2._lastProgressMs).toBeGreaterThanOrEqual(s1._lastProgressMs);
  });

  test("tool.start bumps progress and clears _pendingUserInputSince", () => {
    const s1 = reducer(initialTuiState, { type: "USER_INPUT_SENT" });
    const evt: ToolStartEvent = {
      type: "tool.start", call_id: "c1", tool: "Bash", args_preview: "ls",
    };
    const s2 = reducer(s1, { type: "EVENT", event: evt });
    expect(s2._pendingUserInputSince).toBeNull();
    expect(s2.toolLane).toHaveLength(1);
  });

  test("tool.complete bumps progress", async () => {
    const s1 = reducer(initialTuiState, {
      type: "EVENT",
      event: {
        type: "tool.start", call_id: "c1", tool: "Bash", args_preview: "ls",
      } as ToolStartEvent,
    });
    const t1 = s1._lastProgressMs;
    await new Promise((r) => setTimeout(r, 2));
    const evt: ToolCompleteEvent = {
      type: "tool.complete", call_id: "c1", tool: "Bash",
      ok: true, result_preview: "a\nb\n", duration_ms: 10,
    };
    const s2 = reducer(s1, { type: "EVENT", event: evt });
    expect(s2._lastProgressMs).toBeGreaterThan(t1);
  });

  test("status heartbeat does NOT bump _lastProgressMs", async () => {
    // Set baseline by sending user input
    const s1 = reducer(initialTuiState, { type: "USER_INPUT_SENT" });
    const t1 = s1._lastProgressMs;
    await new Promise((r) => setTimeout(r, 10));

    // A status event arrives — model is still working but no deltas
    const evt: StatusUpdateEvent = {
      type: "status", model: "m", profile: "default",
      elapsed_seconds: 5, tokens_up: 100, tokens_down: 0,
      tool_summary: "",
    };
    const s2 = reducer(s1, { type: "EVENT", event: evt });
    // Crucial: progress timestamp UNCHANGED. Otherwise the
    // detector would never fire on a slow stream.
    expect(s2._lastProgressMs).toBe(t1);
  });

  test("message.append (assistant content) bumps progress", () => {
    const s1 = reducer(initialTuiState, { type: "USER_INPUT_SENT" });
    const evt: MessageAppendEvent = {
      type: "message.append", role: "assistant", content: "hi",
    };
    const s2 = reducer(s1, { type: "EVENT", event: evt });
    expect(s2._pendingUserInputSince).toBeNull();
    expect(s2._lastProgressMs).toBeGreaterThanOrEqual(s1._lastProgressMs);
  });

  test("idle state stays idle — no events, no progress changes", () => {
    // initialTuiState has _lastProgressMs=0 and _pendingUserInputSince=null
    expect(initialTuiState._lastProgressMs).toBe(0);
    expect(initialTuiState._pendingUserInputSince).toBeNull();
  });
});
