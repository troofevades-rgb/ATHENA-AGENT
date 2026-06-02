/**
 * Top-of-screen banner — minimal Claude-Code / Codex-style splash
 * with the athena twist: the braille owl is the brand mark, beside a
 * quiet info block.
 *
 * Deliberately spare: no block wordmark, no tool catalog, no dividers
 * or nested borders. Just the owl + a centered identity/model/cwd/
 * tips column, single accent color, lots of whitespace. On narrow
 * terminals the owl drops and the info block spans the row.
 */

import { Box } from "ink";
import React from "react";

import type { BannerEvent } from "../transport/protocol.js";
import { InfoPanel } from "./InfoPanel.js";
import { Owl } from "./Owl.js";

interface BannerProps {
  event: BannerEvent;
  termCols: number;
  termRows: number;
}

const MIN_OWL_WIDTH = 32;
const PANEL_HEIGHT_FALLBACK = 22; // photo-owl path only
// Floor for the minimal banner height so the info column (identity +
// model/cwd/theme + commands ≈ 8 lines) always has room even if the
// owl mark is shorter.
const MIN_PANEL_ROWS = 9;

function _Banner({
  event,
  termCols,
}: BannerProps): React.JSX.Element {
  const palette = event.palette ?? defaultPalette();
  // Owl shows when there's either a photo matrix OR braille/ASCII art.
  const hasOwl =
    event.owl_pixels !== null || (event.owl_art?.length ?? 0) > 0;
  // Width/height of the owl's art mark (for panel sizing when there's
  // no photo matrix to measure).
  const owlArtW =
    event.owl_art && event.owl_art.length > 0
      ? Math.max(...event.owl_art.map((r) => r.length))
      : 0;
  const owlArtH = event.owl_art?.length ?? 0;
  // Layout: [outer paddingX=1] [owl panel] [gap=1] [info panel]
  //         [outer paddingX=1]. outer paddingX comes from main.tsx.
  const OUTER_PADDING = 2;
  const GAP = 3; // breathing room between the owl mark and the text
  // Side-by-side needs room for the owl beside a ≥30-wide info block.
  // The braille mark is a FIXED width (can't gracefully downscale),
  // so require its full width to fit; the photo path can size down.
  // Below the threshold, drop the owl and let info span full width.
  const owlNeed = event.owl_pixels
    ? MIN_OWL_WIDTH * 2 + 4
    : owlArtW + GAP + 30 + OUTER_PADDING;
  const sideBySide = hasOwl && termCols >= owlNeed;
  // Banner height tracks the content. The braille mark is now compact
  // (~10 rows); forcing the old 22-row panel would float it in empty
  // space. Photo path keeps the taller fallback.
  const panelHeight = event.owl_pixels
    ? Math.max(PANEL_HEIGHT_FALLBACK, event.owl_pixels.height + 2)
    : Math.max(owlArtH, MIN_PANEL_ROWS);
  // Outer width consumed by the owl mark (no border now — it floats).
  const owlPanelOuterW = sideBySide
    ? (event.owl_pixels ? event.owl_pixels.width + 4 : owlArtW)
    : 0;
  const infoPanelOuterW = sideBySide
    ? Math.max(30, termCols - owlPanelOuterW - GAP - OUTER_PADDING)
    : Math.max(30, termCols - OUTER_PADDING);

  return (
    <Box marginTop={1} flexDirection="row" gap={3} alignItems="center">
      {sideBySide && (
        <Owl
          art={event.owl_art}
          pixels={event.owl_pixels}
          palette={palette}
          width={owlArtW + 4}
          maxHeight={panelHeight}
          height={panelHeight}
        />
      )}
      {/* Info block vertically centered against the (taller) owl so
         the short text column sits balanced beside the mark rather
         than pinned to the top. */}
      <InfoPanel
        model={event.model}
        cwd={event.cwd}
        themeName={palette.name}
        commandsHint={event.commands_hint}
        palette={palette}
        height={panelHeight}
        width={infoPanelOuterW}
      />
    </Box>
  );
}

function defaultPalette(): BannerEvent["palette"] {
  return {
    name: "phosphor",
    description: "fallback",
    primary: "green",
    primary_dim: "green",
    primary_faint: "green",
    accent: "yellow",
    accent_dim: "yellow",
    gradient: [],
  };
}


/**
 * React.memo around Banner — the splash shouldn't re-render on every
 * StatusUpdateEvent (which arrives every turn). Shallow equality on
 * the event prop is fine; banner data only changes when theme or
 * model swaps, and React handles those refs cleanly.
 */
export const Banner = React.memo(_Banner);
