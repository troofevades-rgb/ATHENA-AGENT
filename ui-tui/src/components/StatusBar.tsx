/**
 * StatusBar — pinned to the bottom of the screen.
 *
 * Layout: ``justifyContent="space-between"`` so identity sits
 * pinned-left and counters sit pinned-right. Reads cleanly at
 * any terminal width because the middle just stretches.
 */

import { Box, Text } from "ink";
import React from "react";

import type {
  StatusUpdateEvent,
  ThemePalette,
} from "../transport/protocol.js";
import { renderSparkline } from "../hooks/useTokenRate.js";

interface StatusBarProps {
  status: StatusUpdateEvent | null;
  palette: ThemePalette;
  /** Token-per-second history (oldest → newest) for the right-side
   * sparkline. Empty array hides the sparkline gracefully. */
  tpsHistory?: number[];
  /** Current tps for the inline label next to the sparkline. */
  tpsCurrent?: number;
  /** Terminal width in columns. Used to drop optional segments
   * (theme name, sparkline, tokens) when the bar would otherwise
   * wrap. Default 999 = no shrinking. */
  termCols?: number;
}

export function StatusBar({
  status,
  palette,
  tpsHistory = [],
  tpsCurrent = 0,
  termCols = 999,
}: StatusBarProps): React.JSX.Element {
  if (!status) {
    return (
      <Box>
        <Text color={palette.primary_faint}>…</Text>
      </Box>
    );
  }
  // Width tiers — at each smaller terminal size we drop more
  // optional segments. The MODEL name + elapsed + tokens are the
  // core; everything else degrades first.
  const showTheme = termCols >= 100;
  const showSparkline = termCols >= 90;
  const showTools = termCols >= 80;
  const showContext = termCols >= 72;
  const showProfile = termCols >= 70;
  const showTokens = termCols >= 60;
  const leftSegments: React.JSX.Element[] = [];
  if (status.model) {
    leftSegments.push(
      <Text key="prompt" color={palette.accent}>
        ▰▰{" "}
      </Text>,
    );
    leftSegments.push(
      <Text key="model" color={palette.accent_dim}>
        {status.model}
      </Text>,
    );
  }
  if (status.profile && showProfile) {
    leftSegments.push(
      <Text key="profile" color={palette.primary_dim}>
        {" · "}
        {status.profile}
      </Text>,
    );
  }
  if (status.tool_summary && showTools) {
    leftSegments.push(
      <Text key="tools" color={palette.primary_dim}>
        {" · "}
        {status.tool_summary}
      </Text>,
    );
  }

  const rightSegments: React.JSX.Element[] = [];
  if (status.elapsed_seconds !== undefined && status.elapsed_seconds !== null) {
    rightSegments.push(
      <Text key="elapsed" color={palette.primary_dim}>
        {formatDuration(status.elapsed_seconds)}
      </Text>,
    );
  }
  const hasTokens =
    (status.tokens_up !== undefined && status.tokens_up !== null) ||
    (status.tokens_down !== undefined && status.tokens_down !== null);
  if (hasTokens && showTokens) {
    rightSegments.push(
      <Text key="tokens" color={palette.primary_dim}>
        {rightSegments.length > 0 ? " · " : ""}
        {"↑"}
        {(status.tokens_up ?? 0).toLocaleString()}
        {" ↓"}
        {(status.tokens_down ?? 0).toLocaleString()}
      </Text>,
    );
  }
  // Context-window gauge — "ctx ████░░░░ 45%". Tracks live context
  // occupancy against the model window; color escalates as usage nears
  // the auto-compact watermark (comfortable → approaching → imminent),
  // so the user can see a compaction coming.
  if (
    showContext &&
    status.context_used != null &&
    status.context_limit != null &&
    status.context_limit > 0
  ) {
    const pct = Math.min(1, Math.max(0, status.context_used / status.context_limit));
    const compactAt = status.context_compact_ratio ?? null;
    const WIDTH = 8;
    const filled = Math.max(0, Math.min(WIDTH, Math.round(pct * WIDTH)));
    const bar = "█".repeat(filled) + "░".repeat(WIDTH - filled);
    const color =
      compactAt != null && pct >= compactAt
        ? palette.accent
        : compactAt != null && pct >= compactAt * 0.9
          ? palette.accent_dim
          : palette.primary_dim;
    rightSegments.push(
      <Text key="ctx">
        <Text color={palette.primary_faint}>
          {rightSegments.length > 0 ? " · " : ""}ctx{" "}
        </Text>
        <Text color={color}>
          {bar} {Math.round(pct * 100)}%
        </Text>
      </Text>,
    );
  }

  // TPS sparkline + current rate.
  //
  // Show as soon as we've seen ANY activity ever (any nonzero sample
  // in history). Once it appears it persists — even when current=0
  // it's useful to see the rolling-window context ("model has been
  // idle for ~5 buckets but was busy before"). Prior version hid
  // the sparkline anytime current dropped to 0, which made it
  // flicker in/out during the natural between-turns idle.
  const hasEverHadActivity =
    tpsHistory.length > 0 && tpsHistory.some((v) => v > 0);
  if (hasEverHadActivity && showSparkline) {
    const spark = renderSparkline(tpsHistory);
    const rateText = tpsCurrent >= 1
      ? `${Math.round(tpsCurrent)}/s`
      : tpsCurrent > 0
        ? `${tpsCurrent.toFixed(1)}/s`
        : "idle";  // explicit when current rate is zero
    const rateColor = tpsCurrent > 0
      ? palette.accent_dim
      : palette.primary_faint;
    rightSegments.push(
      <Text key="tps">
        <Text color={palette.primary_faint}>{" · "}</Text>
        <Text color={palette.accent_dim}>{spark}</Text>
        <Text color={rateColor}>{" "}{rateText}</Text>
      </Text>,
    );
  }
  // Theme name on the far right — reclaims the info we dropped when
  // the "athena — <theme>" subtitle was removed from the banner.
  // Faint so it sits as a label, not a competing data point.
  // First to go when the terminal is narrow.
  if (showTheme) {
    rightSegments.push(
      <Text key="theme" color={palette.primary_faint}>
        {rightSegments.length > 0 ? "  ·  " : ""}
        {palette.name}
      </Text>,
    );
  }

  return (
    <Box justifyContent="space-between">
      <Box>{leftSegments}</Box>
      <Box>{rightSegments}</Box>
    </Box>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return s > 0 ? `${m}m${s}s` : `${m}m`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return m > 0 ? `${h}h${m}m` : `${h}h`;
}
