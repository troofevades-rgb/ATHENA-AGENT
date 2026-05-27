import { describe, expect, test } from "bun:test";

import {
  appendFilter,
  filterThinkBlocks,
  initialThinkFilterState,
} from "./thinkBlocks.js";

describe("filterThinkBlocks", () => {
  test("passes plain text unchanged", () => {
    expect(filterThinkBlocks("Hello world")).toBe("Hello world");
    expect(filterThinkBlocks("")).toBe("");
  });

  test("collapses a closed think block into past-tense marker", () => {
    const input = "<think>walk through the steps</think>The answer is 42.";
    expect(filterThinkBlocks(input)).toBe("· (thought)The answer is 42.");
  });

  test("collapses an unclosed think block into a live spinner", () => {
    const input = "Before <think>thinking out loud, not done yet";
    expect(filterThinkBlocks(input)).toBe("Before · thinking…");
  });

  test("handles multiple closed blocks", () => {
    const input =
      "Hello <think>first thought</think>middle<think>second</think>end";
    expect(filterThinkBlocks(input)).toBe(
      "Hello · (thought)middle· (thought)end",
    );
  });

  test("preserves text after a closed block when followed by more thinking", () => {
    const input = "<think>a</think>visible<think>b";
    expect(filterThinkBlocks(input)).toBe("· (thought)visible· thinking…");
  });

  test("collapses a think block that's the entire output", () => {
    expect(filterThinkBlocks("<think>nothing else yet")).toBe(
      "· thinking…",
    );
    expect(filterThinkBlocks("<think>complete</think>")).toBe(
      "· (thought)",
    );
  });

  test("survives mid-tag truncation gracefully", () => {
    // A stream that ends mid-open-tag — open tag never matches,
    // so the whole thing flows through as text. (Reasonable;
    // the next delta will complete the tag and the next render
    // will collapse correctly.)
    expect(filterThinkBlocks("Hello <thin")).toBe("Hello <thin");
  });
});

describe("appendFilter (incremental)", () => {
  // Helper: drive the incremental filter over a sequence of deltas
  // the same way the reducer does, and return the final committed
  // streaming buffer.
  function simulate(deltas: readonly string[]): string {
    let buffer = "";
    let state = initialThinkFilterState;
    for (const chunk of deltas) {
      const result = appendFilter(state, chunk);
      const popped = result.popLen > 0
        ? buffer.slice(0, buffer.length - result.popLen)
        : buffer;
      buffer = popped + result.append;
      state = result.state;
    }
    // At end of stream, append any held tail (the reducer does
    // this on stream.end too).
    return buffer + (state.tail || "");
  }

  test("plain text streams through unchanged across deltas", () => {
    expect(simulate(["Hello ", "world"])).toBe("Hello world");
    expect(simulate(["a", "b", "c", "d"])).toBe("abcd");
  });

  // REGRESSION: same-delta open+close was popping LIVE_MARKER.length
  // characters from the consumer's buffer (legitimate prior content),
  // chewing the first ~11 chars of whatever was streamed before.
  // Observed in OSINT session: "Network" → "etwork", "Indicates"
  // → "ndicates", etc.
  test("open + close in the SAME delta does NOT eat prior content", () => {
    // Stream 'Network details: <think>fast</think>more text'
    // as two deltas. The first delta commits 'Network details: '.
    // The second delta opens and closes <think> internally — must
    // not pop any chars from the already-committed 'Network details: '.
    expect(simulate([
      "Network details: ",
      "<think>fast</think>more text",
    ])).toBe("Network details: · (thought)more text");
  });

  test("open across delta boundary, close in next delta — pops correctly", () => {
    // Open in delta 1 (live marker goes to buffer), close in delta 2
    // (must pop the live marker from the buffer and emit done marker).
    expect(simulate([
      "before <think>",
      "thinking happens</think>after",
    ])).toBe("before · (thought)after");
  });

  test("multiple same-delta blocks do not corrupt content", () => {
    expect(simulate([
      "prefix ",
      "<think>a</think>mid<think>b</think>suffix",
    ])).toBe("prefix · (thought)mid· (thought)suffix");
  });

  test("partial tag straddling a delta is held until resolved", () => {
    // Delta 1 ends with "<thin" (partial open). Delta 2 finishes
    // it with "k>foo</think>bar". Output should be "before· (thought)bar".
    expect(simulate([
      "before<thin",
      "k>foo</think>bar",
    ])).toBe("before· (thought)bar");
  });

  test("unclosed block at stream end keeps the live marker", () => {
    expect(simulate(["before<think>", "thinking"])).toBe(
      "before· thinking…",
    );
  });

  test("first delta entirely inside a closing block — pops prior buffer marker", () => {
    // Delta 1 opens, delta 2 contains only the </think>. The pop
    // must remove the live marker from delta 1's contribution to
    // the buffer.
    expect(simulate([
      "x<think>", // appends "x· thinking…", state.liveMarkerLen=11
      "</think>y", // pops 11 chars (the live marker), appends "· (thought)y"
    ])).toBe("x· (thought)y");
  });
});
