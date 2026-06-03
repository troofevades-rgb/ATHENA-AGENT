/**
 * Render tests for renderLine() via ink-testing-library — these assert
 * the ACTUAL rendered output (in-process, no real terminal), covering
 * the tool-tree header (#1) and markdown assistant blocks (#2).
 */

import React from "react";
import { expect, test, describe } from "bun:test";
import { render } from "ink-testing-library";

import { renderLine } from "../components/Transcript.js";
import type { ThemePalette } from "../transport/protocol.js";
import type { TranscriptLine } from "../state/types.js";

const palette: ThemePalette = {
  name: "test", description: "",
  primary: "#0f0", primary_dim: "#0a0", primary_faint: "#060",
  accent: "#fc6", accent_dim: "#a73",
  gradient: [],
};

function frame(line: TranscriptLine): string {
  const { lastFrame } = render(<>{renderLine(line, palette, "#0f0")}</>);
  return lastFrame() ?? "";
}

describe("renderLine — tool tree (#1)", () => {
  test("header renders the ⏺ status dot, tool name, args and duration", () => {
    const out = frame({ key: 1, role: "tool", content: "⏺ Bash(npm test)  34ms" });
    expect(out).toContain("⏺");
    expect(out).toContain("Bash(npm test)");
    expect(out).toContain("34ms");
  });

  test("first body line keeps the ⎿ branch gutter", () => {
    const out = frame({ key: 2, role: "tool", content: "⎿ PASS 12 tests" });
    expect(out).toContain("⎿");
    expect(out).toContain("PASS 12 tests");
  });

  test("file:line reference in body still renders path + line", () => {
    const out = frame({ key: 3, role: "tool", content: "⎿ athena/ui.py:657:def tool_result" });
    expect(out).toContain("athena/ui.py");
    expect(out).toContain(":657");
    expect(out).toContain("def tool_result");
  });
});

describe("renderLine — markdown assistant (#2)", () => {
  test("renders a heading", () => {
    const out = frame({ key: 4, role: "assistant", content: "# Plan\nintro text" });
    expect(out).toContain("Plan");
    expect(out).toContain("intro text");
  });

  test("renders a bulleted list with bullets", () => {
    const out = frame({
      key: 5, role: "assistant", content: "- first item\n- second item",
    });
    expect(out).toContain("•");
    expect(out).toContain("first item");
    expect(out).toContain("second item");
  });

  test("renders an ordered list with numbers", () => {
    const out = frame({
      key: 6, role: "assistant", content: "1. step one\n2. step two",
    });
    expect(out).toContain("step one");
    expect(out).toContain("step two");
    expect(out).toContain("2.");
  });

  test("renders a fenced code block's contents", () => {
    const out = frame({
      key: 7, role: "assistant", content: "before\n```\ncode_line()\n```\nafter",
    });
    expect(out).toContain("code_line()");
    expect(out).toContain("before");
    expect(out).toContain("after");
  });
});
