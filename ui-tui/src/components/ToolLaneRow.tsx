/**
 * <ToolLaneRow> — a single in-flight tool call.
 *
 * Renders:
 *   <spinner>  toolName(args)  · 12s  [still working]
 *
 * The elapsed-time counter re-renders every second via useTicker.
 * The "still working" badge appears once the call has been running
 * for more than ``stillWorkingThresholdMs`` (default 15s) — useful
 * for tools like browser_navigate or osv_check that legitimately
 * take a while, so the user can tell "slow but progressing" from
 * "hung".
 */

import React from "react";
import { Box, Text } from "ink";

import { Spinner } from "./Spinner.js";
import { useTicker } from "../hooks/useTicker.js";
import type { ThemePalette } from "../transport/protocol.js";

interface Props {
  tool: string;
  args: string;
  startedAtMs: number;
  palette: ThemePalette | undefined;
  /** Threshold past which we add the "still working" hint. */
  stillWorkingThresholdMs?: number;
}

export function ToolLaneRow({
  tool,
  args,
  startedAtMs,
  palette,
  stillWorkingThresholdMs = 15_000,
}: Props): React.JSX.Element {
  // 1Hz re-render so the elapsed counter ticks every second.
  useTicker(1000);
  const elapsedMs = Math.max(0, performance.now() - startedAtMs);
  const elapsedSec = Math.floor(elapsedMs / 1000);
  const accent = palette?.accent ?? "yellow";
  const dim = palette?.accent_dim ?? "yellow";
  const faint = palette?.primary_faint ?? "gray";

  const showStillWorking = elapsedMs > stillWorkingThresholdMs;

  return (
    <Box>
      <Spinner color={accent} />
      <Text color={accent}>
        {" "}
        {tool}
      </Text>
      <Text color={dim}>({args})</Text>
      {/* Elapsed counter only appears after the first second so a fast
         tool call doesn't flicker "0s" before completing. */}
      {elapsedSec >= 1 && (
        <Text color={faint}>
          {"  · "}
          {_formatElapsed(elapsedSec)}
        </Text>
      )}
      {showStillWorking && (
        <Text color={dim}>
          {"  "}
          [still working]
        </Text>
      )}
    </Box>
  );
}

function _formatElapsed(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s > 0 ? `${m}m${s}s` : `${m}m`;
}
