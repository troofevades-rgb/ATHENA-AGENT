/**
 * Shared layout primitives extracted from the banner / info
 * panel so the composition reads like a layout document, not
 * a flexbox jungle.
 *
 *   <Divider />  — horizontal rule between sections
 *   <Row />      — label / value row with aligned label column
 *
 * Inspired by the AthenaSplash mockup. The styling is driven
 * by the active ``ThemePalette`` so these primitives recolor
 * with ``/theme set`` like everything else in the TUI.
 */

import { Box, Text } from "ink";
import React from "react";

import type { ThemePalette } from "../transport/protocol.js";

interface DividerProps {
  palette: ThemePalette;
  /** Characters wide. Defaults to filling the parent (1×). */
  width?: number;
}

export function Divider({
  palette,
  width = 38,
}: DividerProps): React.JSX.Element {
  return (
    <Text color={palette.primary_faint}>{"─".repeat(Math.max(1, width))}</Text>
  );
}

interface RowProps {
  /** Left-column label. Padded to ``labelWidth`` chars. */
  label: string;
  /** Right-column value. */
  value: string;
  /** Optional explicit label-column width — when omitted, scales
   * to the label length plus a single space. Pass an explicit
   * width when grouping multiple rows so columns line up. */
  labelWidth?: number;
  labelColor?: string;
  valueColor?: string;
  palette: ThemePalette;
}

export function Row({
  label,
  value,
  labelWidth = 8,
  labelColor,
  valueColor,
  palette,
}: RowProps): React.JSX.Element {
  return (
    <Box>
      <Box width={labelWidth}>
        <Text color={labelColor ?? palette.accent_dim}>{label}</Text>
      </Box>
      <Text color={valueColor ?? palette.primary_dim}>{value}</Text>
    </Box>
  );
}
