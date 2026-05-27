/**
 * Info panel — the right-hand half of the banner. Identity,
 * tool catalog, commands hint.
 *
 * Layout philosophy (adopted from the AthenaSplash mockup):
 *   - Sections separated by ``<Divider />``
 *   - Rows aligned via ``<Row label= value=>`` with consistent
 *     label-column widths within a group
 *   - Tools listed with `·` separators, not commas
 *   - "+9 more" gets its own row, not a "...  +N" suffix
 *   - Width is shared with the owl panel via ``flexGrow``
 *     instead of a hardcoded INFO_WIDTH
 */

import { Box, Text } from "ink";
import React from "react";

import type {
  ThemePalette,
  ToolSetSummary,
} from "../transport/protocol.js";
import { Divider, Row } from "./Layout.js";

interface InfoPanelProps {
  model: string;
  cwd: string;
  themeName: string;
  themeDescription: string;
  tools: ToolSetSummary[];
  commandsHint: string;
  palette: ThemePalette;
  /** Optional explicit width when the parent doesn't use flexGrow. */
  width?: number;
  /** Optional explicit outer height — used to match the owl
   * panel so the side-by-side pair lines up at the bottom. */
  height?: number;
}

const LABEL_WIDTH_IDENTITY = 7;  // "model"/"cwd"/"theme"
const LABEL_WIDTH_TOOLSET = 8;   // "file"/"shell"/"skills"/...

export function InfoPanel({
  model,
  cwd,
  themeName,
  themeDescription,
  tools,
  commandsHint,
  palette,
  width,
  height,
}: InfoPanelProps): React.JSX.Element {
  // Inner content width: subtract 6 (2 border + 4 paddingX={2}),
  // PLUS a safety margin to account for Ink's actual rendered
  // width being narrower than `width` in flex layouts (something
  // along the chain — likely the parent row's gap or another
  // Box's natural sizing — consumes a few extra cells that my
  // chrome calc doesn't see). Without this margin, label/value
  // budgets in tool rows overshoot reality by ~10 cells and Ink
  // wraps mid-word.
  const RENDER_SAFETY_MARGIN = 8;
  const innerW = Math.max(
    20,
    (width ?? 60) - 6 - RENDER_SAFETY_MARGIN,
  );
  const cwdDisplay = elideMiddle(cwd, innerW - LABEL_WIDTH_IDENTITY);

  // Pull the "..." overflow toolset out so we can render it as
  // a dedicated row in the spirit of "+9 more".
  const overflow = tools.find((t) => t.name === "…");
  const visibleTools = tools.filter((t) => t.name !== "…");

  return (
    <Box
      borderStyle="round"
      borderColor={palette.primary_faint}
      flexDirection="column"
      paddingX={2}
      paddingY={1}
      {...(width ? { width } : { flexGrow: 1 })}
      {...(height ? { height } : {})}
    >
      {/* identity header */}
      <Box>
        <Text bold color={palette.accent}>
          athena{" "}
        </Text>
        <Text italic color={palette.primary_dim}>
          · local agentic coder
        </Text>
      </Box>
      <Divider palette={palette} width={innerW} />

      {/* identity rows */}
      <Row
        palette={palette}
        label="model"
        value={model}
        labelWidth={LABEL_WIDTH_IDENTITY}
        valueColor={palette.accent}
      />
      <Row
        palette={palette}
        label="cwd"
        value={cwdDisplay}
        labelWidth={LABEL_WIDTH_IDENTITY}
        valueColor={palette.primary_dim}
      />
      {/* Theme: name on its own row aligned with model/cwd, then
         description as a dim italic line below — no leading
         em-dash, indented under the value column so it reads as
         continuation, not a list item. Avoids the prior single-row
         layout which overflowed and wrapped to "  — …" on Windows
         Terminal at typical widths. */}
      <Row
        palette={palette}
        label="theme"
        value={themeName}
        labelWidth={LABEL_WIDTH_IDENTITY}
        valueColor={palette.primary}
      />
      {/* Leading spaces inside the Text rather than an empty
         <Box width={...} /> spacer — Ink collapses empty Boxes
         in some layouts, which made the description disappear.
         Putting the indent inside the Text node guarantees it
         renders. */}
      {themeDescription && themeDescription.length > 0 && (
        <Box>
          <Text italic color={palette.primary_dim}>
            {" ".repeat(LABEL_WIDTH_IDENTITY)}
            {elideTail(
              themeDescription,
              Math.max(8, innerW - LABEL_WIDTH_IDENTITY),
            )}
          </Text>
        </Box>
      )}

      <Divider palette={palette} width={innerW} />

      {/* tool catalog — section header gets a left bar accent so
         it reads as a section divider, not a row label. */}
      <SectionHeader palette={palette} label="tools" />
      {visibleTools.map((toolset) => {
        const hidden = toolset.hidden_count ?? 0;
        // `·`-separated names instead of comma-separated — cleaner
        // visual rhythm in narrow columns.
        let value = toolset.tools.join(" · ");
        if (hidden > 0) value += `  +${hidden}`;
        const budget = innerW - LABEL_WIDTH_TOOLSET - 2;
        return (
          <Row
            key={toolset.name}
            palette={palette}
            label={toolset.name}
            value={elideTail(value, budget)}
            labelWidth={LABEL_WIDTH_TOOLSET}
            labelColor={palette.primary_dim}
            valueColor={palette.primary_dim}
          />
        );
      })}
      {overflow && (
        // Overflow row reads as a dim summary, not another toolset:
        //   "+9 hidden  agent · browser · code · …"
        // The "(N hidden)" framing makes clear these are tools we
        // chose NOT to show in the catalog above. Lower-contrast
        // colors keep it from competing with the real tool rows.
        <Box marginTop={0}>
          <Text color={palette.accent_dim}>
            +{overflow.hidden_count} hidden
          </Text>
          <Text color={palette.primary_faint}>
            {elideTail(
              overflow.tools.join(" · "),
              innerW - String(`+${overflow.hidden_count} hidden  `).length,
            )}
          </Text>
        </Box>
      )}

      <Divider palette={palette} width={innerW} />

      {/* commands hint */}
      <Box>
        <SectionHeader palette={palette} label="commands" />
        <Text color={palette.primary_dim}>
          {"  "}
          {elideTail(commandsHint, innerW - 12)}
        </Text>
      </Box>
    </Box>
  );
}

// ---- helpers ------------------------------------------------------

/**
 * <SectionHeader> — section divider styled as `▎ label` with a
 * left bar accent in the brightest palette color. Used to break
 * up the InfoPanel into "tools" / "commands" sections without
 * burning a full row on a header line.
 */
function SectionHeader({
  palette,
  label,
}: {
  palette: ThemePalette;
  label: string;
}): React.JSX.Element {
  return (
    <Text>
      <Text color={palette.accent}>▎</Text>
      <Text bold color={palette.accent}>
        {" "}
        {label}
      </Text>
    </Text>
  );
}

function elideTail(s: string, max: number): string {
  if (max <= 1) return s.slice(0, Math.max(1, max));
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}

function elideMiddle(s: string, max: number): string {
  if (max <= 1) return s.slice(0, Math.max(1, max));
  if (s.length <= max) return s;
  const keep = max - 1;
  const left = Math.floor(keep / 2);
  const right = keep - left;
  return s.slice(0, left) + "…" + s.slice(-right);
}
