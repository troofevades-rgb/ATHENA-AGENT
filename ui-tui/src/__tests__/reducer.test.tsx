/**
 * Pure reducer tests — no React, no Ink, just state transitions.
 *
 * INVARIANT: every TranscriptLine = exactly one terminal row.
 * Multi-line content is split at commit time.
 */

import { expect, test, describe } from "bun:test";

import { reducer } from "../state/reducer.js";
import { initialTuiState } from "../state/types.js";
import type {
  BannerEvent, MessageAppendEvent, StreamStartEvent,
  StreamDeltaEvent, StreamEndEvent, ToolStartEvent,
  ToolCompleteEvent, StatusFlashEvent, StatusUpdateEvent,
  ThemeChangeEvent, ThemePalette, ConfirmRequestEvent,
} from "../transport/protocol.js";

const palette: ThemePalette = {
  name: "test", description: "",
  primary: "#fff", primary_dim: "#aaa", primary_faint: "#666",
  accent: "#fc6", accent_dim: "#a73",
  gradient: [],
};

describe("reducer", () => {
  test("banner event sets the banner", () => {
    const e: BannerEvent = {
      type: "banner", model: "m", cwd: "/", theme: "test",
      tools: [], owl_art: [], owl_pixels: null, palette,
      commands_hint: "",
    };
    const next = reducer(initialTuiState, { type: "EVENT", event: e });
    expect(next.banner).toEqual(e);
  });

  test("message.append single line", () => {
    const e: MessageAppendEvent = {
      type: "message.append", role: "system", content: "hello",
    };
    const s1 = reducer(initialTuiState, { type: "EVENT", event: e });
    expect(s1.lines).toHaveLength(1);
    expect(s1.lines[0].role).toBe("system");
    expect(s1.lines[0].content).toBe("hello");
    const s2 = reducer(s1, { type: "EVENT", event: e });
    expect(s2.lines).toHaveLength(2);
    expect(s2.lines[1].key).toBeGreaterThan(s2.lines[0].key);
  });

  test("message.append splits multi-line content into individual rows", () => {
    const e: MessageAppendEvent = {
      type: "message.append", role: "assistant", content: "line1\nline2\nline3",
    };
    const s = reducer(initialTuiState, { type: "EVENT", event: e });
    expect(s.lines).toHaveLength(3);
    expect(s.lines[0].content).toBe("line1");
    expect(s.lines[1].content).toBe("line2");
    expect(s.lines[2].content).toBe("line3");
    expect(s.lines[0].role).toBe("assistant");
  });

  test("stream.start/delta/end commits single-line text as one row", () => {
    const start: StreamStartEvent = {
      type: "stream.start", stream_id: "s1", role: "assistant",
    };
    const delta1: StreamDeltaEvent = {
      type: "stream.delta", stream_id: "s1", text: "hello ",
    };
    const delta2: StreamDeltaEvent = {
      type: "stream.delta", stream_id: "s1", text: "world",
    };
    const end: StreamEndEvent = { type: "stream.end", stream_id: "s1" };
    let s = reducer(initialTuiState, { type: "EVENT", event: start });
    expect(s.streamId).toBe("s1");
    s = reducer(s, { type: "EVENT", event: delta1 });
    s = reducer(s, { type: "EVENT", event: delta2 });
    expect(s.streaming).toBe("hello world");
    s = reducer(s, { type: "EVENT", event: end });
    expect(s.streamId).toBeNull();
    expect(s.streaming).toBe("");
    expect(s.lines).toHaveLength(1);
    expect(s.lines[0].role).toBe("assistant");
    expect(s.lines[0].content).toBe("hello world");
  });

  test("stream.end splits multi-line text into individual rows", () => {
    const start: StreamStartEvent = {
      type: "stream.start", stream_id: "s1", role: "assistant",
    };
    const delta: StreamDeltaEvent = {
      type: "stream.delta", stream_id: "s1", text: "line1\nline2\nline3",
    };
    const end: StreamEndEvent = { type: "stream.end", stream_id: "s1" };
    let s = reducer(initialTuiState, { type: "EVENT", event: start });
    s = reducer(s, { type: "EVENT", event: delta });
    s = reducer(s, { type: "EVENT", event: end });
    expect(s.lines).toHaveLength(3);
    expect(s.lines[0].content).toBe("line1");
    expect(s.lines[2].content).toBe("line3");
  });

  test("stream.end strips thought markers", () => {
    const start: StreamStartEvent = {
      type: "stream.start", stream_id: "s1", role: "assistant",
    };
    const delta: StreamDeltaEvent = {
      type: "stream.delta", stream_id: "s1", text: "· (thought)",
    };
    const end: StreamEndEvent = { type: "stream.end", stream_id: "s1" };
    let s = reducer(initialTuiState, { type: "EVENT", event: start });
    s = reducer(s, { type: "EVENT", event: delta });
    s = reducer(s, { type: "EVENT", event: end });
    // Thought-only content produces no lines
    expect(s.lines).toHaveLength(0);
  });

  test("stream.delta from wrong stream_id is ignored", () => {
    const start: StreamStartEvent = {
      type: "stream.start", stream_id: "s1", role: "assistant",
    };
    const wrong: StreamDeltaEvent = {
      type: "stream.delta", stream_id: "OTHER", text: "junk",
    };
    let s = reducer(initialTuiState, { type: "EVENT", event: start });
    s = reducer(s, { type: "EVENT", event: wrong });
    expect(s.streaming).toBe("");
  });

  test("tool.complete splits into header + body rows", () => {
    const start: ToolStartEvent = {
      type: "tool.start", call_id: "t1", tool: "Read", args_preview: "x.py",
    };
    const done: ToolCompleteEvent = {
      type: "tool.complete", call_id: "t1", tool: "Read",
      ok: true, result_preview: "line1\nline2",
    };
    let s = reducer(initialTuiState, { type: "EVENT", event: start });
    expect(s.toolLane).toHaveLength(1);
    s = reducer(s, { type: "EVENT", event: done });
    expect(s.toolLane).toHaveLength(0);
    // Header + 2 body lines = 3 rows
    expect(s.lines).toHaveLength(3);
    expect(s.lines[0].role).toBe("tool");
    expect(s.lines[0].content).toBe("> Read");
    expect(s.lines[1].content).toBe("  line1");
    expect(s.lines[2].content).toBe("  line2");
  });

  test("tool.complete caps body at 12 lines", () => {
    const body = Array.from({ length: 20 }, (_, i) => `line${i}`).join("\n");
    const done: ToolCompleteEvent = {
      type: "tool.complete", call_id: "t1", tool: "Grep",
      ok: true, result_preview: body,
    };
    const s = reducer(initialTuiState, { type: "EVENT", event: done });
    // Header + 12 shown + 1 overflow marker = 14 rows
    expect(s.lines).toHaveLength(14);
    expect(s.lines[0].content).toBe("> Grep");
    expect(s.lines[13].content).toContain("8 more lines");
  });

  test("status.flash replaces the active flash", () => {
    const f1: StatusFlashEvent = {
      type: "status.flash", text: "first", level: "info", ttl_seconds: 3,
    };
    const f2: StatusFlashEvent = {
      type: "status.flash", text: "second", level: "warn", ttl_seconds: 3,
    };
    let s = reducer(initialTuiState, { type: "EVENT", event: f1 });
    expect(s.flash?.text).toBe("first");
    s = reducer(s, { type: "EVENT", event: f2 });
    expect(s.flash?.text).toBe("second");
    expect(s.flash?.level).toBe("warn");
    s = reducer(s, { type: "DISMISS_FLASH" });
    expect(s.flash).toBeNull();
  });

  test("status update lands in state.status", () => {
    const u: StatusUpdateEvent = {
      type: "status", model: "m", profile: "p",
      elapsed_seconds: 10, tokens_up: 100, tokens_down: 50,
    };
    const s = reducer(initialTuiState, { type: "EVENT", event: u });
    expect(s.status?.tokens_up).toBe(100);
  });

  test("theme.change updates banner palette without reset", () => {
    const banner: BannerEvent = {
      type: "banner", model: "m", cwd: "/", theme: "old",
      tools: [], owl_art: [], owl_pixels: null, palette,
      commands_hint: "",
    };
    let s = reducer(initialTuiState, { type: "EVENT", event: banner });
    const newPalette: ThemePalette = { ...palette, name: "newpal", primary: "#0f0" };
    const themeEvent: ThemeChangeEvent = {
      type: "theme.change", theme: "newpal", palette: newPalette,
    };
    s = reducer(s, { type: "EVENT", event: themeEvent });
    expect(s.banner?.palette.name).toBe("newpal");
    expect(s.banner?.model).toBe("m");
  });

  test("confirm.request shows overlay; DISMISS_CONFIRM clears", () => {
    const req: ConfirmRequestEvent = {
      type: "confirm.request", request_id: "r1",
      prompt: "delete x?", default: false,
    };
    let s = reducer(initialTuiState, { type: "EVENT", event: req });
    expect(s.confirmReq?.request_id).toBe("r1");
    s = reducer(s, { type: "DISMISS_CONFIRM" });
    expect(s.confirmReq).toBeNull();
  });

  test("confirm.request snaps scroll to bottom", () => {
    const scrolledUp = { ...initialTuiState, scrollOffset: 42 };
    const req: ConfirmRequestEvent = {
      type: "confirm.request", request_id: "r2",
      prompt: "allow?", default: true,
    };
    const s = reducer(scrolledUp, { type: "EVENT", event: req });
    expect(s.scrollOffset).toBe(0);
    expect(s.confirmReq?.request_id).toBe("r2");
  });

  test("SET_SCROLL clamps negative offsets to 0", () => {
    const s = reducer(initialTuiState, { type: "SET_SCROLL", offset: -5 });
    expect(s.scrollOffset).toBe(0);
  });

  test("auto-scrolls to bottom on new line when already at bottom", () => {
    let s = { ...initialTuiState, scrollOffset: 0 };
    s = reducer(s, {
      type: "EVENT",
      event: { type: "message.append", role: "system", content: "x" },
    });
    expect(s.scrollOffset).toBe(0);
  });

  test("preserves scroll position on new line when scrolled up", () => {
    let s = { ...initialTuiState, scrollOffset: 5 };
    s = reducer(s, {
      type: "EVENT",
      event: { type: "message.append", role: "system", content: "x" },
    });
    expect(s.scrollOffset).toBe(5);
  });
});
