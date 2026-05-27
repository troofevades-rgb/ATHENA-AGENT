/**
 * Diff component + looksLikeDiff heuristic tests.
 */

import React from "react";
import { render } from "ink-testing-library";
import { expect, test, describe } from "bun:test";

import { Diff, looksLikeDiff } from "../components/Diff.js";

describe("looksLikeDiff", () => {
  test("true for text with @@ hunks", () => {
    expect(looksLikeDiff("@@ -1,3 +1,4 @@\n some context\n+added")).toBe(true);
  });

  test("true for text with --- a/ +++ b/ headers", () => {
    expect(looksLikeDiff("--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@")).toBe(true);
  });

  test("true for text with multiple + / - lines", () => {
    expect(looksLikeDiff("-old1\n-old2\n+new1")).toBe(true);
  });

  test("false for plain text", () => {
    expect(looksLikeDiff("just a regular sentence")).toBe(false);
  });

  test("false for text with single - (subtraction, not deletion)", () => {
    expect(looksLikeDiff("score: -42 points")).toBe(false);
  });
});

describe("Diff", () => {
  test("renders added/removed/hunk lines", () => {
    const src = "@@ -1 +1 @@\n-old line\n+new line";
    const { lastFrame } = render(<Diff text={src} />);
    expect(lastFrame()).toContain("old line");
    expect(lastFrame()).toContain("new line");
    expect(lastFrame()).toContain("@@");
  });
});
