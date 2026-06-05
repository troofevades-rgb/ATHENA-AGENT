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

  test("message.append keeps assistant content as one markdown line", () => {
    const e: MessageAppendEvent = {
      type: "message.append", role: "assistant", content: "line1\nline2\nline3",
    };
    const s = reducer(initialTuiState, { type: "EVENT", event: e });
    // Assistant text is held as one line and rendered as a markdown
    // block (renderLine → <Markdown>), not split into per-row lines.
    expect(s.lines).toHaveLength(1);
    expect(s.lines[0].role).toBe("assistant");
    expect(s.lines[0].content).toBe("line1\nline2\nline3");
  });

  test("message.append splits non-assistant multi-line into rows", () => {
    const e: MessageAppendEvent = {
      type: "message.append", role: "system", content: "line1\nline2\nline3",
    };
    const s = reducer(initialTuiState, { type: "EVENT", event: e });
    expect(s.lines).toHaveLength(3);
    expect(s.lines[0].content).toBe("line1");
    expect(s.lines[2].content).toBe("line3");
    expect(s.lines[0].role).toBe("system");
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

  test("stream.end commits multi-line reply as one markdown line", () => {
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
    // One markdown line carrying the full reply (not split per row).
    expect(s.lines).toHaveLength(1);
    expect(s.lines[0].role).toBe("assistant");
    expect(s.lines[0].content).toBe("line1\nline2\nline3");
  });

  test("TOGGLE_REASONING flips the flag and flashes", () => {
    expect(initialTuiState.showReasoning).toBe(false);
    const on = reducer(initialTuiState, { type: "TOGGLE_REASONING" });
    expect(on.showReasoning).toBe(true);
    expect(on.flash?.text).toBe("reasoning shown");
    const off = reducer(on, { type: "TOGGLE_REASONING" });
    expect(off.showReasoning).toBe(false);
    expect(off.flash?.text).toBe("reasoning hidden");
  });

  test("stream.end hides reasoning by default", () => {
    const end: StreamEndEvent = {
      type: "stream.end", stream_id: "s1",
      final_text: "the answer", thinking: "step one\nstep two",
    };
    const start: StreamStartEvent = {
      type: "stream.start", stream_id: "s1", role: "assistant",
    };
    let s = reducer(initialTuiState, { type: "EVENT", event: start });
    s = reducer(s, { type: "EVENT", event: end });
    // showReasoning is off → only the answer commits, no thinking rows.
    expect(s.lines).toHaveLength(1);
    expect(s.lines[0].role).toBe("assistant");
    expect(s.lines.some((l) => l.role === "thinking")).toBe(false);
  });

  test("stream.end commits reasoning when toggled on", () => {
    const start: StreamStartEvent = {
      type: "stream.start", stream_id: "s1", role: "assistant",
    };
    const end: StreamEndEvent = {
      type: "stream.end", stream_id: "s1",
      final_text: "the answer", thinking: "step one\nstep two",
    };
    let s = reducer(initialTuiState, { type: "TOGGLE_REASONING" });
    s = reducer(s, { type: "EVENT", event: start });
    s = reducer(s, { type: "EVENT", event: end });
    // Header + 2 body rows (role "thinking"), then the answer.
    const thinking = s.lines.filter((l) => l.role === "thinking");
    expect(thinking).toHaveLength(3);
    expect(thinking[0].content).toContain("▾ thinking (2 lines)");
    expect(thinking[1].content).toContain("step one");
    const last = s.lines[s.lines.length - 1];
    expect(last.role).toBe("assistant");
    expect(last.content).toBe("the answer");
  });

  test("stream.end with reasoning on but no thinking commits only the answer", () => {
    const start: StreamStartEvent = {
      type: "stream.start", stream_id: "s1", role: "assistant",
    };
    const end: StreamEndEvent = {
      type: "stream.end", stream_id: "s1", final_text: "answer only",
    };
    let s = reducer(initialTuiState, { type: "TOGGLE_REASONING" });
    s = reducer(s, { type: "EVENT", event: start });
    s = reducer(s, { type: "EVENT", event: end });
    expect(s.lines.some((l) => l.role === "thinking")).toBe(false);
    expect(s.lines).toHaveLength(1);
    expect(s.lines[0].content).toBe("answer only");
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
    // Header + 2 body lines = 3 rows. Header carries the ⏺ dot + args
    // (from tool.start); first body line gets the ⎿ branch gutter.
    expect(s.lines).toHaveLength(3);
    expect(s.lines[0].role).toBe("tool");
    expect(s.lines[0].content).toBe("⏺ Read(x.py)");
    expect(s.lines[1].content).toBe("⎿ line1");
    expect(s.lines[2].content).toBe("  line2");
  });

  test("concurrent same-tool calls keep distinct lanes and pair by call_id", () => {
    // Two skill_view calls in flight at once (parallel dispatch), each
    // with its own call_id. Regression: a name-only pairing made the
    // first completion evict BOTH lane rows and mis-attribute args.
    const startA: ToolStartEvent = {
      type: "tool.start", call_id: "skill_view#1", tool: "skill_view",
      args_preview: "name='debugging'",
    };
    const startB: ToolStartEvent = {
      type: "tool.start", call_id: "skill_view#2", tool: "skill_view",
      args_preview: "name='dogfood'",
    };
    let s = reducer(initialTuiState, { type: "EVENT", event: startA });
    s = reducer(s, { type: "EVENT", event: startB });
    expect(s.toolLane).toHaveLength(2);

    // First completion removes ONLY its own lane row...
    const doneA: ToolCompleteEvent = {
      type: "tool.complete", call_id: "skill_view#1", tool: "skill_view",
      ok: true, result_preview: "debugging body",
    };
    s = reducer(s, { type: "EVENT", event: doneA });
    expect(s.toolLane).toHaveLength(1);
    expect(s.toolLane[0].id).toBe("skill_view#2");
    // ...and uses ITS OWN args, not the other call's.
    expect(s.lines[0].content).toBe("⏺ skill_view(name='debugging')");

    // Second completion clears the lane and uses its own args.
    const doneB: ToolCompleteEvent = {
      type: "tool.complete", call_id: "skill_view#2", tool: "skill_view",
      ok: true, result_preview: "dogfood body",
    };
    s = reducer(s, { type: "EVENT", event: doneB });
    expect(s.toolLane).toHaveLength(0);
    const headerB = s.lines.find((l) => l.content.startsWith("⏺ skill_view(name='dogfood'"));
    expect(headerB).toBeDefined();
  });

  test("tool.complete caps body at 12 lines", () => {
    const body = Array.from({ length: 20 }, (_, i) => `line${i}`).join("\n");
    const done: ToolCompleteEvent = {
      type: "tool.complete", call_id: "t1", tool: "Grep",
      ok: true, result_preview: body,
    };
    const s = reducer(initialTuiState, { type: "EVENT", event: done });
    // Header + 12 shown + 1 overflow marker = 14 rows. No tool.start
    // fired, so the header has no args — just "⏺ Grep".
    expect(s.lines).toHaveLength(14);
    expect(s.lines[0].content).toBe("⏺ Grep");
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
});
