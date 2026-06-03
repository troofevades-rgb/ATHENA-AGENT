/**
 * Render tests for the StatusBar context-window gauge (in-process via
 * ink-testing-library — no terminal needed).
 */

import React from "react";
import { expect, test, describe } from "bun:test";
import { render } from "ink-testing-library";

import { StatusBar } from "../components/StatusBar.js";
import type { StatusUpdateEvent, ThemePalette } from "../transport/protocol.js";

const palette: ThemePalette = {
  name: "test", description: "",
  primary: "#0f0", primary_dim: "#0a0", primary_faint: "#060",
  accent: "#fc6", accent_dim: "#a73",
  gradient: [],
};

function frameOf(status: StatusUpdateEvent): string {
  const { lastFrame } = render(
    <StatusBar status={status} palette={palette} termCols={120} />,
  );
  return lastFrame() ?? "";
}

describe("StatusBar context gauge", () => {
  test("renders a bar + percentage when context fields are present", () => {
    const out = frameOf({
      type: "status", model: "m",
      context_used: 14746, context_limit: 32768, context_compact_ratio: 0.75,
    });
    expect(out).toContain("ctx");
    expect(out).toContain("45%");
    // The bar uses block/▁ glyphs.
    expect(out).toMatch(/[█░]/);
  });

  test("is absent when context fields are missing", () => {
    const out = frameOf({ type: "status", model: "m", tokens_up: 10 });
    expect(out).not.toContain("ctx");
  });

  test("clamps and still renders at/over the compaction watermark", () => {
    const out = frameOf({
      type: "status", model: "m",
      context_used: 40000, context_limit: 32768, context_compact_ratio: 0.75,
    });
    // Over the window → clamped to 100%, still drawn (not crashed/blank).
    expect(out).toContain("100%");
    expect(out).toContain("ctx");
  });

  test("hidden on a narrow terminal", () => {
    const { lastFrame } = render(
      <StatusBar
        status={{ type: "status", model: "m", context_used: 100, context_limit: 1000 }}
        palette={palette}
        termCols={50}
      />,
    );
    expect(lastFrame() ?? "").not.toContain("ctx");
  });
});
