/**
 * StuckIndicator — shows a warning when a turn has stalled.
 *
 * When the agent has been "in flight" (waiting for the model's first
 * reply, or mid-stream, or mid-tool-call) but no progress event has
 * arrived in `stuckThresholdMs` (default 30s), surface a hint that
 * the user can press ESC to interrupt.
 *
 * Common causes of a stall:
 *   - Local Ollama auto-unloaded the model and is reloading it
 *   - GPU is thrashing / the model is spilling to CPU
 *   - The HTTP connection to the provider is dead-waiting
 *   - An MCP tool is hanging on its own dead read
 *
 * Without this indicator the user has no signal — a slow model
 * looks identical to a hung process.
 */

import { Box, Text } from "ink";
import React from "react";

import { useTicker } from "../hooks/useTicker.js";
import type { ThemePalette } from "../transport/protocol.js";
import type { TuiState } from "../state/types.js";

interface StuckIndicatorProps {
  state: TuiState;
  palette: ThemePalette;
  /** Milliseconds without a progress event before we show the
   * warning. Default 30s. */
  stuckThresholdMs?: number;
}

export function StuckIndicator({
  state,
  palette,
  stuckThresholdMs = 30_000,
}: StuckIndicatorProps): React.JSX.Element | null {
  // Re-render every second so the elapsed-stuck counter updates.
  useTicker(1000);

  // Are we even waiting for a response?
  const inFlight =
    state.streamId !== null ||
    state.toolLane.length > 0 ||
    state._pendingUserInputSince !== null;
  if (!inFlight) return null;

  // Use the most recent of: last progress, the pending-input
  // timestamp, or the start of any in-flight tool. This catches
  // the "just sent user input, model hasn't even started" case AND
  // the "stream started 90s ago but no deltas" case.
  const referencePoints: number[] = [];
  if (state._lastProgressMs > 0) referencePoints.push(state._lastProgressMs);
  if (state._pendingUserInputSince !== null) {
    referencePoints.push(state._pendingUserInputSince);
  }
  for (const t of state.toolLane) {
    referencePoints.push(t.startedAtMs);
  }
  if (referencePoints.length === 0) return null;

  // The most-recent reference: time since "anything happened."
  const mostRecent = Math.max(...referencePoints);
  const stuckMs = performance.now() - mostRecent;
  if (stuckMs < stuckThresholdMs) return null;

  const stuckSeconds = Math.round(stuckMs / 1000);
  return (
    <Box>
      <Text color={palette.primary_faint}>· </Text>
      <Text color={palette.accent_dim}>stalled {stuckSeconds}s</Text>
      <Text color={palette.primary_faint}> — press ESC to interrupt</Text>
    </Box>
  );
}
