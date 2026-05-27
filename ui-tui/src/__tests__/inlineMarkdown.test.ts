/**
 * Inline markdown parser — bold / italic / code / URL extraction
 * for one line of assistant text.
 */

import { describe, expect, test } from "bun:test";

import { parseInline } from "../stream/inlineMarkdown.js";


describe("parseInline", () => {
  test("plain text passes through as a single segment", () => {
    expect(parseInline("hello world")).toEqual([
      { text: "hello world" },
    ]);
  });

  test("empty input yields empty array", () => {
    expect(parseInline("")).toEqual([]);
  });

  test("recognizes bold **...** with surrounding text", () => {
    expect(parseInline("a **bold** b")).toEqual([
      { text: "a " },
      { text: "bold", bold: true },
      { text: " b" },
    ]);
  });

  test("recognizes italic *...* with surrounding text", () => {
    expect(parseInline("a *italic* b")).toEqual([
      { text: "a " },
      { text: "italic", italic: true },
      { text: " b" },
    ]);
  });

  test("recognizes inline `code`", () => {
    expect(parseInline("the `foo` call")).toEqual([
      { text: "the " },
      { text: "foo", code: true },
      { text: " call" },
    ]);
  });

  test("bold takes priority over italic at the same position", () => {
    // ** ... ** should be bold, not two italics around an empty middle
    const segs = parseInline("**both**");
    expect(segs).toEqual([{ text: "both", bold: true }]);
  });

  test("recognizes http URL and strips trailing punctuation", () => {
    const segs = parseInline("see https://example.com.");
    expect(segs).toEqual([
      { text: "see " },
      { text: "https://example.com", url: true },
      { text: "." },
    ]);
  });

  test("recognizes https URL", () => {
    const segs = parseInline("https://www.usaspending.gov/foo");
    expect(segs).toEqual([
      { text: "https://www.usaspending.gov/foo", url: true },
    ]);
  });

  test("multiple URLs in one line", () => {
    const segs = parseInline("a https://x.com and https://y.com here");
    expect(segs.filter((s) => s.url).map((s) => s.text)).toEqual([
      "https://x.com",
      "https://y.com",
    ]);
  });

  test("inline code containing * does not break parsing", () => {
    const segs = parseInline("use `str | None` not `Optional[str]`");
    expect(segs).toEqual([
      { text: "use " },
      { text: "str | None", code: true },
      { text: " not " },
      { text: "Optional[str]", code: true },
    ]);
  });

  test("unterminated ** falls through to literal", () => {
    // No closing ** — must NOT eat to end of string
    const segs = parseInline("a **bold but no close");
    expect(segs).toEqual([{ text: "a **bold but no close" }]);
  });

  test("unterminated backtick falls through to literal", () => {
    const segs = parseInline("a `code but no close");
    expect(segs).toEqual([{ text: "a `code but no close" }]);
  });

  test("preserves nested-looking but non-nested markers", () => {
    // Real-world: "*one* and *two*"
    const segs = parseInline("*one* and *two*");
    expect(segs).toEqual([
      { text: "one", italic: true },
      { text: " and " },
      { text: "two", italic: true },
    ]);
  });

  test("does not produce empty segments", () => {
    const segs = parseInline("****");
    // Empty bold should be dropped
    expect(segs.every((s) => s.text.length > 0)).toBe(true);
  });

  test("mix of all four token kinds", () => {
    const segs = parseInline("a `code` *it* **bold** see https://x.com");
    const kinds = segs
      .map((s) =>
        s.code ? "code" : s.bold ? "bold" : s.italic ? "italic" : s.url ? "url" : "plain",
      )
      .filter((k) => k !== "plain");
    expect(kinds).toEqual(["code", "italic", "bold", "url"]);
  });

  test("URL stripping does not over-eat — only common trailing punctuation", () => {
    expect(parseInline("https://x.com/a)b").filter((s) => s.url)).toEqual([
      // The ) at the end IS stripped; the /a)b in the middle is kept
      { text: "https://x.com/a)b", url: true },
    ]);
    expect(parseInline("https://x.com/foo)").filter((s) => s.url)).toEqual([
      { text: "https://x.com/foo", url: true },
    ]);
  });
});
