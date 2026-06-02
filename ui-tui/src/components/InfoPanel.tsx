/**
 * Info block — the quiet right-hand column of the minimal banner.
 *
 * Claude-Code / Codex feel: no border, no dividers, no tool catalog.
 * Just an identity line (the spark + "athena"), the essentials
 * (model, cwd, theme) and a one-line commands hint — vertically
 * centered so the short column sits balanced beside the taller owl
 * mark. Single accent color; everything else dim.
 */

import { Box, Text } from "ink";
import React from "react";

import type { ThemePalette } from "../transport/protocol.js";
import { Row } from "./Layout.js";

interface InfoPanelProps {
  model: string;
  cwd: string;
  themeName: string;
  commandsHint: string;
  palette: ThemePalette;
  /** Optional explicit width when the parent doesn't use flexGrow. */
  width?: number;
  /** Optional explicit outer height — matches the owl mark so the
   * pair is vertically balanced. */
  height?: number;
}

const LABEL_WIDTH = 6; // "model" / "cwd" / "theme"

export function InfoPanel({
  model,
  cwd,
  themeName,
  commandsHint,
  palette,
  width,
  height,
}: InfoPanelProps): React.JSX.Element {
  // Inner content width for elision. paddingX={1} on each side.
  const innerW = Math.max(20, (width ?? 60) - 2);
  const cwdDisplay = elideMiddle(cwd, innerW - LABEL_WIDTH);

  return (
    <Box
      flexDirection="column"
      justifyContent="center"
      paddingX={1}
      {...(width ? { width } : { flexGrow: 1 })}
      {...(height ? { height } : {})}
    >
      {/* identity line — the spark is the athena twist */}
      <Box>
        <Text color={palette.accent}>✦ </Text>
        <Text bold color={palette.accent}>
          athena
        </Text>
        <Text italic color={palette.primary_dim}>
          {"  ·  local agentic coder"}
        </Text>
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Row
          palette={palette}
          label="model"
          value={model}
          labelWidth={LABEL_WIDTH}
          labelColor={palette.primary_faint}
          valueColor={palette.primary}
        />
        <Row
          palette={palette}
          label="cwd"
          value={cwdDisplay}
          labelWidth={LABEL_WIDTH}
          labelColor={palette.primary_faint}
          valueColor={palette.primary_dim}
        />
        <Row
          palette={palette}
          label="theme"
          value={themeName}
          labelWidth={LABEL_WIDTH}
          labelColor={palette.primary_faint}
          valueColor={palette.primary_dim}
        />
      </Box>

      <Box marginTop={1}>
        <Text color={palette.primary_faint}>
          {elideTail(commandsHint, innerW)}
        </Text>
      </Box>
    </Box>
  );
}

// ---- helpers ------------------------------------------------------

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
