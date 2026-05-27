/**
 * useInputHistory — shell-style up/down navigation.
 *
 * Tests the pure logic. Wrapping in renderHook would be heavier than
 * needed since the hook is small and synchronous; we exercise its
 * API directly via a tiny React harness.
 */

import { describe, expect, test } from "bun:test";
import { render } from "ink-testing-library";
import React from "react";

import {
  useInputHistory,
  type InputHistoryAPI,
} from "../hooks/useInputHistory.js";


/** Tiny harness: render a no-op component that exposes the hook API
 * through a ref-like getter so tests can call methods directly. */
function makeHistory(): InputHistoryAPI {
  let api: InputHistoryAPI | undefined;
  function Harness(): React.ReactElement {
    api = useInputHistory();
    return React.createElement("div", null, "");
  }
  render(React.createElement(Harness));
  // ink-testing-library renders synchronously; api is populated
  if (!api) throw new Error("hook did not mount");
  return api;
}


describe("useInputHistory", () => {
  test("empty history: prev returns null", () => {
    const h = makeHistory();
    expect(h.navigatePrev("")).toBeNull();
    expect(h.navigatePrev("draft text")).toBeNull();
  });

  test("commit then prev recalls most recent entry", () => {
    const h = makeHistory();
    h.commit("first");
    h.commit("second");
    expect(h.navigatePrev("")).toBe("second");
  });

  test("repeated prev walks older", () => {
    const h = makeHistory();
    h.commit("one");
    h.commit("two");
    h.commit("three");
    expect(h.navigatePrev("")).toBe("three");
    expect(h.navigatePrev("")).toBe("two");
    expect(h.navigatePrev("")).toBe("one");
    // At oldest — further prev returns null
    expect(h.navigatePrev("")).toBeNull();
  });

  test("next from middle of history walks newer", () => {
    const h = makeHistory();
    h.commit("a");
    h.commit("b");
    h.commit("c");
    h.navigatePrev("");  // → "c"
    h.navigatePrev("");  // → "b"
    expect(h.navigateNext()).toBe("c");
  });

  test("next from newest restores the draft", () => {
    const h = makeHistory();
    h.commit("committed");
    expect(h.navigatePrev("my draft")).toBe("committed");
    // Step back to bottom — should restore "my draft"
    expect(h.navigateNext()).toBe("my draft");
  });

  test("next from not-navigating is a no-op", () => {
    const h = makeHistory();
    h.commit("x");
    // Haven't navigated up yet
    expect(h.navigateNext()).toBeNull();
  });

  test("commit dedupes immediately-previous entry", () => {
    const h = makeHistory();
    h.commit("same");
    h.commit("same");
    h.commit("same");
    // Only one entry in history → prev once works, twice returns null
    expect(h.navigatePrev("")).toBe("same");
    expect(h.navigatePrev("")).toBeNull();
  });

  test("commit does NOT dedupe non-adjacent duplicates", () => {
    const h = makeHistory();
    h.commit("a");
    h.commit("b");
    h.commit("a");  // not adjacent to previous "a"
    expect(h.navigatePrev("")).toBe("a");
    expect(h.navigatePrev("")).toBe("b");
    expect(h.navigatePrev("")).toBe("a");
  });

  test("commit empty string is a no-op", () => {
    const h = makeHistory();
    h.commit("");
    expect(h.navigatePrev("")).toBeNull();
  });

  test("reset abandons in-progress navigation", () => {
    const h = makeHistory();
    h.commit("first");
    h.navigatePrev("");  // → "first"
    h.reset();
    // After reset, navigateNext is a no-op (we're back to live draft)
    expect(h.navigateNext()).toBeNull();
    // And navigatePrev restarts from current draft
    expect(h.navigatePrev("brand new")).toBe("first");
  });

  test("draft survives prev → next → typing → reset → prev", () => {
    const h = makeHistory();
    h.commit("old");
    expect(h.navigatePrev("partial")).toBe("old");
    expect(h.navigateNext()).toBe("partial");
    // User types something different — reset is called
    h.reset();
    // ↑ now stashes the NEW draft
    expect(h.navigatePrev("brand new draft")).toBe("old");
    expect(h.navigateNext()).toBe("brand new draft");
  });

  // -------------------------------------------------------------
  // searchPrev / cancelSearch / acceptSearch — Ctrl+R semantics
  // -------------------------------------------------------------

  test("searchPrev returns null on empty history", () => {
    const h = makeHistory();
    expect(h.searchPrev("foo", "")).toBeNull();
  });

  test("searchPrev returns null on empty query", () => {
    const h = makeHistory();
    h.commit("anything");
    expect(h.searchPrev("", "draft")).toBeNull();
  });

  test("searchPrev finds the most-recent matching entry", () => {
    const h = makeHistory();
    h.commit("write the alpha module");
    h.commit("now beta");
    h.commit("test alpha again");
    h.commit("unrelated");
    expect(h.searchPrev("alpha", "")).toBe("test alpha again");
  });

  test("searchPrev with same query walks to next older match", () => {
    const h = makeHistory();
    h.commit("foo one");
    h.commit("bar");
    h.commit("foo two");
    h.commit("baz");
    // First call: most recent "foo" entry
    expect(h.searchPrev("foo", "")).toBe("foo two");
    // Second call with SAME query: next older "foo" entry
    expect(h.searchPrev("foo", "")).toBe("foo one");
    // Third call: no more
    expect(h.searchPrev("foo", "")).toBeNull();
  });

  test("changing query restarts the search from the end", () => {
    const h = makeHistory();
    h.commit("alpha 1");
    h.commit("beta");
    h.commit("alpha 2");
    h.searchPrev("alpha", "");  // → "alpha 2"
    h.searchPrev("alpha", "");  // → "alpha 1"
    // Now switch query
    expect(h.searchPrev("beta", "")).toBe("beta");
  });

  test("searchPrev case-insensitive", () => {
    const h = makeHistory();
    h.commit("ALPHA query");
    expect(h.searchPrev("alpha", "")).toBe("ALPHA query");
  });

  test("substring match (not just prefix)", () => {
    const h = makeHistory();
    h.commit("now show me the file structure");
    expect(h.searchPrev("file", "")).toBe("now show me the file structure");
  });

  test("cancelSearch restores the stashed draft", () => {
    const h = makeHistory();
    h.commit("matched");
    h.searchPrev("match", "in-progress draft text");
    expect(h.cancelSearch()).toBe("in-progress draft text");
    // Restoring twice returns "" (state is cleared)
    expect(h.cancelSearch()).toBe("");
  });

  test("acceptSearch clears state WITHOUT restoring draft", () => {
    const h = makeHistory();
    h.commit("matched");
    h.searchPrev("match", "draft");
    h.acceptSearch();
    // After accept, draft is gone — next prev re-stashes new draft
    expect(h.navigatePrev("new draft")).toBe("matched");
    expect(h.navigateNext()).toBe("new draft");
  });

  test("Ctrl+R during active ↑-nav preserves the original draft", () => {
    // Regression: previously searchPrev unconditionally stashed
    // editor.text as the draft. If the user pressed ↑ first
    // (recalling a history entry into the editor) then Ctrl+R,
    // the recalled history entry was stashed as "draft", so
    // Esc-cancel restored the wrong text.
    const h = makeHistory();
    h.commit("real draft text was this");
    h.commit("alpha entry");
    h.commit("beta entry");
    // User typed nothing, pressed ↑ once → recalls most recent
    expect(h.navigatePrev("")).toBe("beta entry");
    // Then pressed Ctrl+R searching for "alpha" — editor.text
    // is now "beta entry" because ↑ replaced it
    expect(h.searchPrev("alpha", "beta entry")).toBe("alpha entry");
    // Esc cancels the search — should restore the ORIGINAL draft
    // (empty string), not the recalled "beta entry"
    expect(h.cancelSearch()).toBe("");
  });

  test("reset clears search state too", () => {
    const h = makeHistory();
    h.commit("x");
    h.searchPrev("x", "draft");
    h.reset();
    // After reset, fresh search restarts from end
    expect(h.searchPrev("x", "new draft")).toBe("x");
  });

  test("history caps at maxEntries", () => {
    // Need a small cap to test feasibly
    let api: InputHistoryAPI | undefined;
    function Harness(): React.ReactElement {
      api = useInputHistory(3);
      return React.createElement("div", null, "");
    }
    render(React.createElement(Harness));
    if (!api) throw new Error("not mounted");
    api.commit("a");
    api.commit("b");
    api.commit("c");
    api.commit("d");  // pushes "a" off the end
    api.commit("e");  // pushes "b" off the end
    // Walking back should return e, d, c, then null (a and b are gone)
    expect(api.navigatePrev("")).toBe("e");
    expect(api.navigatePrev("")).toBe("d");
    expect(api.navigatePrev("")).toBe("c");
    expect(api.navigatePrev("")).toBeNull();
  });
});
