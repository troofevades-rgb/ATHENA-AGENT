/**
 * Owl panel — renders either the bundled photo (preferred) or
 * the ASCII art (fallback) inside a bordered box.
 *
 * Photo path
 * ----------
 * The gateway ships ``BannerEvent.owl_pixels``: a row-major
 * matrix of ``[topHex, bottomHex]`` cells already sized for the
 * terminal. Each cell renders as ``▀`` with truecolor FG (top
 * source pixel) + BG (bottom source pixel). With Pillow's
 * Lanczos resample on the Python side and Ink's truecolor
 * rendering here, the result is photo-grade.
 *
 * ASCII fallback
 * --------------
 * When ``owl_pixels`` is missing (Pillow not installed, image
 * file lost, etc.) we render the artist's ASCII characters with
 * a character-preserving downscale and two-tone coloring. The
 * silhouette survives at any panel size.
 */

import { Box, Text } from "ink";
import React, { useMemo } from "react";

import type {
  OwlPixelMatrix,
  ThemePalette,
} from "../transport/protocol.js";

interface OwlProps {
  art: string[];
  pixels: OwlPixelMatrix | null;
  palette: ThemePalette;
  /** Outer width of the panel including border + padding. */
  width: number;
  /** Maximum row count for the panel content. */
  maxHeight: number;
  /** Optional explicit outer height for the panel — used to
   * match the info panel so the side-by-side pair bottom-aligns. */
  height?: number;
}

// ---- ASCII fallback bookkeeping ------------------------------------

const INK_WEIGHT: Record<string, number> = {
  " ": 0,
  ".": 1, ",": 1,
  ":": 2, ";": 2,
  "-": 3,
  "=": 4, "+": 4,
  "*": 6,
  "%": 7,
  "#": 8,
  "@": 9,
};

function tone(ch: string): "body" | "field" | "blank" {
  if (ch === " ") return "blank";
  if ("#@%*:;-.,".includes(ch)) return "body";
  return "field";
}

export function downscaleArt(
  rows: string[],
  maxW: number,
  maxH: number,
): string[] {
  if (rows.length === 0 || maxW <= 0 || maxH <= 0) return rows;
  const srcH = rows.length;
  const srcW = Math.max(...rows.map((r) => r.length));
  if (srcW <= maxW && srcH <= maxH) return rows;
  const s = Math.max(srcW / maxW, srcH / maxH);
  const newW = Math.max(1, Math.floor(srcW / s));
  const newH = Math.max(1, Math.floor(srcH / s));
  const out: string[] = [];
  for (let y = 0; y < newH; y++) {
    const y0 = Math.floor(y * s);
    const y1 = Math.max(y0 + 1, Math.floor((y + 1) * s));
    let line = "";
    for (let x = 0; x < newW; x++) {
      const x0 = Math.floor(x * s);
      const x1 = Math.max(x0 + 1, Math.floor((x + 1) * s));
      line += pickRepresentative(rows, y0, y1, x0, x1, srcH, srcW);
    }
    out.push(line);
  }
  return out;
}

function pickRepresentative(
  rows: string[],
  y0: number,
  y1: number,
  x0: number,
  x1: number,
  srcH: number,
  srcW: number,
): string {
  let best = " ";
  let bestWeight = -1;
  for (let sy = y0; sy < Math.min(y1, srcH); sy++) {
    const row = rows[sy] ?? "";
    for (let sx = x0; sx < Math.min(x1, srcW); sx++) {
      const ch = row[sx] ?? " ";
      const w = INK_WEIGHT[ch] ?? 5;
      if (w > bestWeight) {
        best = ch;
        bestWeight = w;
      }
    }
  }
  return best;
}

// ---- Shared outer wrapper -------------------------------------------

/**
 * <OwlPanel> — the bordered card that wraps either render variant
 * (PhotoOwl or AsciiOwl). Extracted so border/padding/bg style
 * changes happen in one place instead of two.
 */
function OwlPanel({
  palette,
  width,
  height,
  children,
}: {
  palette: ThemePalette;
  width?: number;
  height?: number;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <Box
      borderStyle="round"
      borderColor={palette.primary_faint}
      flexDirection="column"
      paddingX={1}
      // When the caller knows the inner content's exact cell width
      // (PhotoOwl knows owl_pixels.width), use a fixed outer width
      // sized to fit it snugly — eliminates the empty-side-margin
      // look caused by ``flexGrow`` stretching the panel wider than
      // the photo. Falls back to flexGrow for the ASCII variant
      // where we don't know the exact cell width.
      {...(width ? { width } : { flexGrow: 1 })}
      alignItems="center"
      {...(height ? { height } : {})}
    >
      {children}
    </Box>
  );
}

// ---- Photo path ------------------------------------------------------

function PhotoOwl({
  pixels,
  palette,
  width,
  height,
}: {
  pixels: OwlPixelMatrix;
  palette: ThemePalette;
  width: number;
  height?: number;
}): React.JSX.Element {
  // Each cell carries [glyph, fgHex, bgHex] — the glyph is a
  // Unicode quadrant block encoding which of the 2×2 source
  // pixels go to FG vs BG. With quadrant rendering we get 4
  // source pixels per cell (vs 2 for half-blocks), so the image
  // doubles in horizontal detail at the same cell count.
  const lines = pixels.cells.map((row, rowIdx) => {
    const cells = row.map((tuple, colIdx) => {
      const glyph = tuple[0] ?? " ";
      const fg = tuple[1] ?? "#000000";
      const bg = tuple[2] ?? fg;
      return (
        <Text key={colIdx} color={fg} backgroundColor={bg}>
          {glyph}
        </Text>
      );
    });
    return <Box key={rowIdx}>{cells}</Box>;
  });
  // Outer panel width = photo width + 4 (2 border + 2 padding).
  // Keeps the bordered card snug around the image instead of
  // stretching to fill the flex row and leaving empty side
  // margins around the owl.
  const panelOuterW = pixels.width + 4;
  return (
    <OwlPanel palette={palette} width={panelOuterW} height={height}>
      {lines}
    </OwlPanel>
  );
}

// ---- ASCII fallback ------------------------------------------------

function AsciiOwl({
  art,
  palette,
  width,
  maxHeight,
  height,
}: {
  art: string[];
  palette: ThemePalette;
  width: number;
  maxHeight: number;
  height?: number;
}): React.JSX.Element | null {
  const innerW = Math.max(1, width - 4);
  const innerH = Math.max(1, maxHeight - 2);
  const rendered = useMemo(
    () => downscaleArt(art, innerW, innerH),
    [art, innerW, innerH],
  );
  if (rendered.length === 0) return null;
  const lines = rendered.map((row, rowIdx) => {
    const spans: React.JSX.Element[] = [];
    let runStart = 0;
    let runTone = tone(row[0] ?? " ");
    for (let i = 1; i <= row.length; i++) {
      const t = i < row.length ? tone(row[i] ?? " ") : null;
      if (t !== runTone) {
        const segment = row.slice(runStart, i);
        spans.push(renderSpan(segment, runTone, palette, `${rowIdx}-${runStart}`));
        runStart = i;
        if (t !== null) runTone = t;
      }
    }
    return <Box key={rowIdx}>{spans}</Box>;
  });
  return <OwlPanel palette={palette} height={height}>{lines}</OwlPanel>;
}

function renderSpan(
  segment: string,
  segTone: "body" | "field" | "blank",
  palette: ThemePalette,
  key: string,
): React.JSX.Element {
  if (segTone === "blank") {
    return <Text key={key}>{segment}</Text>;
  }
  const color = segTone === "body" ? palette.accent : palette.primary_faint;
  return (
    <Text key={key} color={color}>
      {segment}
    </Text>
  );
}

// ---- Public component -----------------------------------------------

export function Owl({
  art,
  pixels,
  palette,
  width,
  maxHeight,
  height,
}: OwlProps): React.JSX.Element | null {
  if (pixels && pixels.cells.length > 0) {
    return <PhotoOwl pixels={pixels} palette={palette} width={width} height={height} />;
  }
  return (
    <AsciiOwl
      art={art}
      palette={palette}
      width={width}
      maxHeight={maxHeight}
      height={height}
    />
  );
}
