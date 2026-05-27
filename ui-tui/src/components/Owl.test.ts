/**
 * Unit tests for ``downscaleArt``. Run with ``bun test``.
 *
 * The current rendering approach is character-preserving: each
 * output cell holds the DENSEST character from its source
 * region (NOT a block-shading ramp glyph). These tests verify
 * that the source characters survive the downscale instead of
 * being averaged into shaded blocks.
 */

import { describe, expect, test } from "bun:test";

import { downscaleArt } from "./Owl.js";

describe("downscaleArt", () => {
  test("returns rows unchanged when target is larger than source", () => {
    const src = ["####", " ## ", "####"];
    const out = downscaleArt(src, 100, 100);
    expect(out).toEqual(src);
  });

  test("returns empty array when input is empty", () => {
    expect(downscaleArt([], 10, 10)).toEqual([]);
  });

  test("returns input when target dimensions are zero or negative", () => {
    const src = ["####", " ## "];
    expect(downscaleArt(src, 0, 10)).toEqual(src);
    expect(downscaleArt(src, 10, 0)).toEqual(src);
    expect(downscaleArt(src, -1, 10)).toEqual(src);
  });

  test("downscaled all-# field preserves # in every output cell", () => {
    // 10×10 source of all # — every output cell should be #,
    // never a block-shading glyph like █ ▓ ▒.
    const src = Array.from({ length: 10 }, () => "##########");
    const out = downscaleArt(src, 5, 5);
    expect(out.length).toBe(5);
    for (const row of out) {
      for (const ch of row ?? "") {
        expect(ch).toBe("#");
      }
    }
  });

  test("downscaled all-blank field maps to space", () => {
    const src = Array.from({ length: 10 }, () => "          ");
    const out = downscaleArt(src, 5, 5);
    for (const row of out) {
      for (const ch of row ?? "") {
        expect(ch).toBe(" ");
      }
    }
  });

  test("densest character wins region representation", () => {
    // 2-row source: middle col mostly ``=`` (background), but
    // each row's middle is replaced by a single ``@`` in
    // alternating positions. The downscale should surface the
    // ``@`` since it outweighs ``=``.
    const src = [
      "====@=====",
      "=====@====",
    ];
    const out = downscaleArt(src, 1, 1);
    // One cell, source region spans the full 10×2 — the @ wins.
    expect(out).toEqual(["@"]);
  });

  test("output character set is a subset of input character set", () => {
    // Regression for the prior block-shading bug: no ``█ ▓ ▒ ░``
    // glyph should appear in the output if the source didn't
    // contain it.
    const src = Array.from(
      { length: 20 },
      () => "=+=+=+#@#@%*=+=+=+#@#@%*=+=+=+",
    );
    const out = downscaleArt(src, 5, 5);
    const srcChars = new Set(src.join(""));
    for (const row of out) {
      for (const ch of row ?? "") {
        expect(srcChars.has(ch)).toBe(true);
      }
    }
  });
});
