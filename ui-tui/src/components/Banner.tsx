/**
 * Top-of-screen banner — wordmark, then owl + info side by side.
 *
 * Adopted the AthenaSplash mockup's layout philosophy:
 *   - Both panels use ``flexGrow={1}`` and share width via Ink's
 *     ``gap`` prop instead of a hardcoded INFO_WIDTH.
 *   - Equal explicit height on both panels so the side-by-side
 *     pair has a flat bottom edge regardless of inner content.
 *   - On narrow terminals (< MIN_OWL_WIDTH), the owl is dropped
 *     and the info panel takes the full row.
 */

import { Box, Text } from "ink";
import React from "react";

import type { BannerEvent } from "../transport/protocol.js";
import { InfoPanel } from "./InfoPanel.js";
import { Owl } from "./Owl.js";
import { Wordmark } from "./Wordmark.js";

const SPRAY_CAP = "▒▒";
const SPRAY_FILL_MAX = 46;
const SPRAY_FILL_MIN = 12;

interface BannerProps {
  event: BannerEvent;
  termCols: number;
  termRows: number;
}

const MIN_OWL_WIDTH = 32;
const PANEL_HEIGHT_FALLBACK = 22;

function _Banner({
  event,
  termCols,
  termRows,
}: BannerProps): React.JSX.Element {
  const palette = event.palette ?? defaultPalette();
  // Side-by-side mode requires at least 2× MIN_OWL_WIDTH +
  // some breathing room. Below that, drop the owl and let the
  // info panel span the full terminal width.
  const sideBySide =
    termCols >= MIN_OWL_WIDTH * 2 + 4 && event.owl_pixels !== null;
  const panelHeight = Math.max(
    PANEL_HEIGHT_FALLBACK,
    event.owl_pixels ? event.owl_pixels.height + 2 : PANEL_HEIGHT_FALLBACK,
  );
  // Compute the InfoPanel's actual outer width so its internal
  // elision budgets match reality. Without this, InfoPanel falls
  // back to (60 - 6) = 54 cells of inner width, which overshoots
  // the rendered width by ~10 cells on typical terminals and
  // causes mid-word wrapping in the "commands" and "+9 hidden"
  // rows.
  //
  // Layout we're computing against:
  //   [outer paddingX=1] [owl panel] [gap=1] [info panel] [outer paddingX=1]
  // outer paddingX comes from main.tsx; the panels are inside it.
  const OUTER_PADDING = 2;
  const GAP = 1;
  const owlPanelOuterW =
    sideBySide && event.owl_pixels ? event.owl_pixels.width + 4 : 0;
  const infoPanelOuterW = sideBySide
    ? Math.max(30, termCols - owlPanelOuterW - GAP - OUTER_PADDING)
    : Math.max(30, termCols - OUTER_PADDING);

  return (
    <Box flexDirection="column">
      {/* No "athena — <theme>" subtitle above the wordmark — it
         duplicates the "athena · local agentic coder" header inside
         InfoPanel and the theme name shown in the theme row, and
         on standard-height terminals (~40 rows) it pushed total
         banner+panels+composer height past the terminal row count
         so Ink clipped it anyway. */}
      <Wordmark palette={palette} termCols={termCols} />
      {/* SPRAY_FILL band below the wordmark — faint caps + solid block
         center, in primary cyan. Width scales with terminal so the
         band tracks the wordmark's perceived width: full bar on wide
         terminals, compact bar on narrow ones. */}
      <Box alignItems="center" justifyContent="center">
        <Text>
          <Text color={palette.primary_faint}>{SPRAY_CAP}</Text>
          <Text color={palette.primary}>
            {"█".repeat(
              Math.max(
                SPRAY_FILL_MIN,
                Math.min(SPRAY_FILL_MAX, termCols - 8),
              ),
            )}
          </Text>
          <Text color={palette.primary_faint}>{SPRAY_CAP}</Text>
        </Text>
      </Box>
      <Box marginTop={1} flexDirection="row" gap={1} alignItems="flex-start">
        {sideBySide && (
          <Owl
            art={event.owl_art}
            pixels={event.owl_pixels}
            palette={palette}
            // ``flexGrow`` is set inside ``Owl`` via its own Box;
            // ``width`` here is the maximum content width we
            // expect (used by the photo renderer for cell-cap).
            width={Math.floor((termCols - 4) / 2)}
            maxHeight={panelHeight}
            // Same explicit height as the InfoPanel so the two
            // cards bottom-align — without this, the owl panel
            // takes its content's natural height (driven by
            // owl_pixels.height) which usually overshoots the
            // info panel's content and leaves an unfinished
            // ragged-bottom look.
            height={panelHeight}
          />
        )}
        <InfoPanel
          model={event.model}
          cwd={event.cwd}
          themeName={palette.name}
          themeDescription={palette.description}
          tools={event.tools}
          commandsHint={event.commands_hint}
          palette={palette}
          height={panelHeight}
          // Explicit width matches the panel's actual rendered
          // outer width — keeps the internal elision budgets in
          // sync with reality so labels don't get clipped or
          // wrapped mid-word.
          width={infoPanelOuterW}
        />
      </Box>
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
