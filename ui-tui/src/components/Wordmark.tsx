/**
 * "ATHENA" wordmark — block-letter title at the top of the banner.
 *
 * Three responsive variants picked from ``termCols``:
 *
 *   wide   (≥ 56 cols): full 6-row ANSI Shadow blocks (50 wide)
 *   medium (≥ 26 cols): single-row spaced title ``▰▰ A T H E N A ▰▰``
 *   narrow (< 26 cols): plain bold ``athena``
 *
 * The wide variant is the brand "look"; the medium and narrow
 * variants are graceful fallbacks so a small terminal doesn't
 * render a visually-broken wordmark.
 *
 * Design history (so we don't repeat dead ends):
 *
 *   1. ANSI Shadow font (first try) — broke on Windows console
 *      fonts due to mismatched cell widths between `█` and shadow
 *      glyphs. Re-adopted after font compatibility improved
 *      (Windows Terminal + Cascadia/Fira Code).
 *   2. Plain blocks + per-row colors — top rows colored with
 *      `palette.accent` rendered invisibly in some Windows Terminal
 *      fonts. Replaced with a 3-tone gradient using colors all
 *      well above any shadow threshold.
 *   3. ink-big-text (cfonts) — `cfonts` loads font JSONs via a
 *      dynamic `require()` that Bun's bundler can't trace, so the
 *      bundled main.js had no font data and rendered empty.
 */

import { Box, Text } from "ink";
import React from "react";

import { useTicker } from "../hooks/useTicker.js";
import type { ThemePalette } from "../transport/protocol.js";

// Custom hand-crafted "neon tube" letterform — hollow outlines with
// a soft glow filling the interior. Built specifically for the
// noctua palette (electric cyan + ice). Outline chars render in
// bright accent; interior ░ chars render in dim primary_faint to
// look like the glow inside a glass tube. Junction nodes (╋ at
// crossbars, ╻╹ at tube ends) give it a hand-routed circuit feel
// that no figlet font matches.
//
// Layout (per-row totals must equal 47 cells exactly):
//
//   <letter A: 7 cells> <gap: 1> <T: 7> <gap: 1> <H: 7> <gap: 1>
//   <E: 7> <gap: 1> <N: 7> <gap: 1> <A: 7>     →  47 cells
//
// Each letter pattern is ALWAYS 7 cells wide (with its own leading
// AND trailing padding space) so concatenation lines up regardless
// of which letter follows.
const _LETTER_A = [
  " ┏━━━┓ ",
  " ┃░░░┃ ",
  " ┃░░░┃ ",
  " ┣━━━┫ ",
  " ┃░░░┃ ",
  " ╹░░░╹ ",
];
const _LETTER_T = [
  "━━━━━━━",
  "░░░╻░░░",
  "░░░┃░░░",
  "░░░┃░░░",
  "░░░┃░░░",
  "░░░╹░░░",
];
const _LETTER_H = [
  " ╻░░░╻ ",
  " ┃░░░┃ ",
  " ┃░░░┃ ",
  " ┣━━━┫ ",
  " ┃░░░┃ ",
  " ╹░░░╹ ",
];
const _LETTER_E = [
  " ┏━━━┓ ",
  " ┃░░░╹ ",
  " ┣━━━╸ ",
  " ┃░░░░ ",
  " ┃░░░╻ ",
  " ┗━━━┛ ",
];
const _LETTER_N = [
  " ╻░░░╻ ",
  " ┃╲░░┃ ",
  " ┃░╲░┃ ",
  " ┃░░╲┃ ",
  " ┃░░░┃ ",
  " ╹░░░╹ ",
];

// Build WORDMARK_ROWS programmatically so per-row length stays
// exactly 47 chars by construction (caught the off-by-three padding
// bug in the literal version). Letters joined with a single-char
// gap; each letter is already 7 cells with its own padding.
const _WORDMARK_LETTERS = [_LETTER_A, _LETTER_T, _LETTER_H, _LETTER_E, _LETTER_N, _LETTER_A];
const WORDMARK_ROWS: readonly string[] = Array.from({ length: 6 }, (_, rowIdx) =>
  _WORDMARK_LETTERS.map((letter) => letter[rowIdx] ?? "").join(" "),
);

const BREAKPOINT_WIDE = 56;    // below this → medium variant
const BREAKPOINT_MEDIUM = 26;  // below this → narrow variant

interface WordmarkProps {
  palette: ThemePalette;
  /** Current terminal width in cells. Drives which variant to
   * render so the wordmark never overflows a narrow terminal. */
  termCols: number;
}

export function Wordmark({
  palette,
  termCols,
}: WordmarkProps): React.JSX.Element {
  if (termCols >= BREAKPOINT_WIDE) return <WordmarkFull palette={palette} />;
  if (termCols >= BREAKPOINT_MEDIUM)
    return <WordmarkMedium palette={palette} />;
  return <WordmarkNarrow palette={palette} />;
}

// ANSI Shadow uses two glyph classes: solid block (`█`, the letter
// body) and double-line drawing chars (`╔╗╚╝║═`, the shadow outline).
// We render the block class brighter than the shadow class, AND
// animate both through the palette's gradient — left-to-right wave
// that gives the wordmark a flowing-light effect instead of static
// monochrome blocks.
// Two-class glyph rendering: bright "tube" outline + dim "glow"
// interior. The dim chars (`░`) fill the inside of each letter to
// simulate the soft light of a neon tube; the outline (everything
// else) is the bright tube wall.
const SHADOW_GLYPHS: ReadonlySet<string> = new Set([
  "░",
]);

// Pre-computed column ranges for each letter in the neon-tube
// letterform. Each letter is 7 cols wide, 1 col gap between, so:
// A=0-6, T=8-14, H=16-22, E=24-30, N=32-38, A=40-46. Total 47.
const LETTER_RANGES: readonly [number, number][] = [
  [0,  7],   // A
  [8,  15],  // T
  [16, 23],  // H
  [24, 31],  // E
  [32, 39],  // N
  [40, 47],  // A
];

/** Map a column index in a WORDMARK_ROWS string to its letter index
 * (0..5), or -1 for spaces between letters. */
function _letterAt(col: number): number {
  for (let i = 0; i < LETTER_RANGES.length; i++) {
    const range = LETTER_RANGES[i];
    if (!range) continue;
    const [start, end] = range;
    if (col >= start && col < end) return i;
  }
  return -1;
}

interface Segment {
  text: string;
  kind: "block" | "shadow" | "space";
  letterIdx: number;
}

/** Split a row into runs of (kind, letterIdx) — each run becomes
 * one `<Text>` so we can color and bold them independently. */
function _segmentRow(row: string): Segment[] {
  const out: Segment[] = [];
  let cur = "";
  let curKind: Segment["kind"] | null = null;
  let curLetter: number | null = null;
  for (let i = 0; i < row.length; i++) {
    const ch = row[i] ?? " ";
    const kind: Segment["kind"] =
      ch === " " ? "space" : SHADOW_GLYPHS.has(ch) ? "shadow" : "block";
    const letterIdx = _letterAt(i);
    if (cur && (kind !== curKind || letterIdx !== curLetter)) {
      out.push({ text: cur, kind: curKind!, letterIdx: curLetter! });
      cur = "";
    }
    cur += ch;
    curKind = kind;
    curLetter = letterIdx;
  }
  if (cur) {
    out.push({ text: cur, kind: curKind!, letterIdx: curLetter! });
  }
  return out;
}

function WordmarkFull({ palette }: { palette: ThemePalette }): React.JSX.Element {
  // ~2 Hz color shift — slow enough to read each color, fast enough
  // to feel alive without being distracting.
  const tick = useTicker(500);

  // Build a usable gradient. If the palette doesn't define one, fall
  // back to a synthesized gradient from the named bright colors.
  const gradient: readonly string[] =
    palette.gradient && palette.gradient.length >= 3
      ? palette.gradient
      : [palette.accent, palette.primary, palette.primary_dim,
         palette.primary, palette.accent];

  // For each letter, pick a color from the gradient offset by the
  // letter's position + the current tick. Letters shift through the
  // gradient as time advances → "wave of light" effect.
  const blockColor = (letterIdx: number): string => {
    if (letterIdx < 0) return palette.accent;
    const idx = (letterIdx + tick) % gradient.length;
    return gradient[idx] ?? palette.accent;
  };

  // Shadow chars get a dimmer cyan — separating them from the bright
  // blocks gives each letter visible inner detail. We use a fixed
  // dim color rather than walking the gradient so the depth stays
  // consistent while the bright tops shift.
  const shadowColor = palette.primary_faint || palette.primary_dim;

  return (
    <Box flexDirection="column" alignItems="center">
      {WORDMARK_ROWS.map((row, rowIdx) => {
        const segs = _segmentRow(row);
        return (
          <Text key={rowIdx}>
            {segs.map((s, j) => {
              if (s.kind === "space") {
                return <Text key={j}>{s.text}</Text>;
              }
              if (s.kind === "shadow") {
                return (
                  <Text key={j} color={shadowColor}>
                    {s.text}
                  </Text>
                );
              }
              return (
                <Text key={j} bold color={blockColor(s.letterIdx)}>
                  {s.text}
                </Text>
              );
            })}
          </Text>
        );
      })}
    </Box>
  );
}

function WordmarkMedium({ palette }: { palette: ThemePalette }): React.JSX.Element {
  // Compact masthead for terminals too narrow for the 50-cell
  // block art. Spaced-letter title with chevrons gives it a
  // distinct shape vs body text without depending on multi-row
  // block glyphs.
  return (
    <Box justifyContent="center">
      <Text bold color={palette.accent}>
        ▰▰{"  "}A T H E N A{"  "}▰▰
      </Text>
    </Box>
  );
}

function WordmarkNarrow({ palette }: { palette: ThemePalette }): React.JSX.Element {
  // Last-resort variant for terminals so narrow that even the
  // medium variant would overflow. Plain bold lowercase title.
  return (
    <Box justifyContent="center">
      <Text bold color={palette.accent}>
        athena
      </Text>
    </Box>
  );
}
