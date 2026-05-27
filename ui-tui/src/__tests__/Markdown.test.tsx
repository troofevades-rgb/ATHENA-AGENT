/**
 * Markdown component tests via ink-testing-library.
 *
 * These render the component and snapshot the visible frame —
 * loose-text assertions rather than DOM, because Ink renders to
 * a string-of-cells. We assert that key elements appear, not the
 * pixel-perfect output (which depends on terminal width).
 */

import React from "react";
import { render } from "ink-testing-library";
import { expect, test, describe } from "bun:test";

import { Markdown } from "../components/Markdown.js";

describe("Markdown", () => {
  test("plain text renders verbatim", () => {
    const { lastFrame } = render(<Markdown text="hello world" />);
    expect(lastFrame()).toContain("hello world");
  });

  test("heading renders with prefix", () => {
    const { lastFrame } = render(<Markdown text="# big header" />);
    expect(lastFrame()).toContain("big header");
    expect(lastFrame()).toContain("#");
  });

  test("bold content is preserved", () => {
    const { lastFrame } = render(<Markdown text="**bold text**" />);
    expect(lastFrame()).toContain("bold text");
    expect(lastFrame()).not.toContain("**");
  });

  test("italic content is preserved", () => {
    const { lastFrame } = render(<Markdown text="*italic text*" />);
    expect(lastFrame()).toContain("italic text");
  });

  test("inline code preserved", () => {
    const { lastFrame } = render(<Markdown text="run `foo()` now" />);
    expect(lastFrame()).toContain("foo()");
    expect(lastFrame()).toContain("now");
  });

  test("fenced code block renders all lines", () => {
    const src = "before\n\`\`\`\nline1\nline2\n\`\`\`\nafter";
    const { lastFrame } = render(<Markdown text={src} />);
    expect(lastFrame()).toContain("line1");
    expect(lastFrame()).toContain("line2");
    expect(lastFrame()).toContain("before");
    expect(lastFrame()).toContain("after");
  });

  test("unordered list renders bullets", () => {
    const src = "- one\n- two\n- three";
    const { lastFrame } = render(<Markdown text={src} />);
    expect(lastFrame()).toContain("one");
    expect(lastFrame()).toContain("two");
    expect(lastFrame()).toContain("three");
    expect(lastFrame()).toContain("•");
  });

  test("ordered list preserves numbering", () => {
    const src = "1. first\n2. second";
    const { lastFrame } = render(<Markdown text={src} />);
    expect(lastFrame()).toContain("1.");
    expect(lastFrame()).toContain("first");
    expect(lastFrame()).toContain("2.");
    expect(lastFrame()).toContain("second");
  });

  test("blockquote renders with prefix", () => {
    const { lastFrame } = render(<Markdown text="> quoted text" />);
    expect(lastFrame()).toContain("quoted text");
    expect(lastFrame()).toContain("│");
  });
});
