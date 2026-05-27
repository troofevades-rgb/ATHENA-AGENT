/**
 * SET_SCROLL clamping — both ends.
 *
 * Regression: previously SET_SCROLL only clamped at 0 (no negative
 * offset). Scrolling up past the oldest committed line accumulated
 * offset unboundedly — a single PageDown couldn't return the user
 * to the bottom because scrollOffset was, e.g., 500 when there were
 * only 30 lines. PageDown subtracts ``visibleBudget`` per press, so
 * the user had to mash it repeatedly.
 *
 * After the fix: SET_SCROLL also caps at ``state.lines.length`` so
 * scrolling past the top is a no-op (already at top) and a single
 * PageDown / Esc gets back to the bottom.
 */

import { describe, expect, test } from "bun:test";

import { reducer } from "../state/reducer.js";
import { initialTuiState } from "../state/types.js";
import type { TranscriptLine } from "../state/types.js";


function stateWithNLines(n: number) {
  const lines: TranscriptLine[] = [];
  for (let i = 0; i < n; i++) {
    lines.push({ key: i, role: "assistant", content: `line ${i}` });
  }
  return { ...initialTuiState, lines };
}


describe("SET_SCROLL clamping", () => {
  test("lower bound: clamps negative to 0", () => {
    const s = stateWithNLines(50);
    const next = reducer(s, { type: "SET_SCROLL", offset: -10 });
    expect(next.scrollOffset).toBe(0);
  });

  test("upper bound: clamps at lines.length", () => {
    const s = stateWithNLines(30);
    const next = reducer(s, { type: "SET_SCROLL", offset: 9999 });
    expect(next.scrollOffset).toBe(30);
  });

  test("within bounds: passes through unchanged", () => {
    const s = stateWithNLines(50);
    const next = reducer(s, { type: "SET_SCROLL", offset: 17 });
    expect(next.scrollOffset).toBe(17);
  });

  test("scrolling up past oldest does NOT keep accumulating", () => {
    // The bug: shift+↑ 1000 times → scrollOffset = 1000 even
    // though only 30 lines exist. Then PageDown -=20 needs 50
    // presses to get back. With the fix, scrollOffset never
    // exceeds 30.
    let s = stateWithNLines(30);
    for (let i = 0; i < 1000; i++) {
      s = reducer(s, { type: "SET_SCROLL", offset: s.scrollOffset + 1 });
    }
    expect(s.scrollOffset).toBe(30);
  });

  test("PageDown from max returns to bottom in one press", () => {
    // The user pressed PageUp to top; then one PageDown should
    // get them back to the bottom. This was broken without the
    // upper-bound clamp.
    let s = stateWithNLines(30);
    s = reducer(s, { type: "SET_SCROLL", offset: 30 });  // at top
    expect(s.scrollOffset).toBe(30);
    // One PageDown of, say, 20 visible rows
    s = reducer(s, { type: "SET_SCROLL", offset: s.scrollOffset - 20 });
    expect(s.scrollOffset).toBe(10);
    // Another PageDown of 20 → should land at 0 (bottom), not -10
    s = reducer(s, { type: "SET_SCROLL", offset: s.scrollOffset - 20 });
    expect(s.scrollOffset).toBe(0);
  });

  test("Esc-to-bottom (offset=0) is always a valid no-op or clamp", () => {
    // Esc when scrolled-up dispatches SET_SCROLL offset=0
    const s = stateWithNLines(50);
    const scrolled = reducer(s, { type: "SET_SCROLL", offset: 25 });
    const reset = reducer(scrolled, { type: "SET_SCROLL", offset: 0 });
    expect(reset.scrollOffset).toBe(0);
  });

  test("empty transcript: any offset clamps to 0", () => {
    const empty = stateWithNLines(0);
    const next = reducer(empty, { type: "SET_SCROLL", offset: 100 });
    expect(next.scrollOffset).toBe(0);
  });
});
