/**
 * <PulsingCursor> — the streaming-text caret.
 *
 * Solid block (▌) while text is actively streaming. When the
 * stream is paused (no delta in the last ~400ms), the caret
 * pulses at 2Hz so the user reads "waiting, not stuck."
 *
 * Host passes `lastDeltaAtMs` (monotonic timestamp of last
 * stream.delta arrival); the component decides solid-vs-pulse
 * by comparing to current time.
 */

import React from "react";
import { Text } from "ink";

import { useTicker } from "../hooks/useTicker.js";

interface Props {
  /** When was the last delta seen (performance.now() value)?
   * Null/undefined means no stream — render nothing. */
  lastDeltaAtMs: number | null;
  /** Render-as-solid threshold. If a delta arrived within this
   * many ms, the cursor is solid. */
  solidWindowMs?: number;
  color?: string;
}

export function PulsingCursor({
  lastDeltaAtMs, solidWindowMs = 400, color,
}: Props): React.JSX.Element | null {
  // 2Hz pulse during idle.
  const tick = useTicker(250);
  if (lastDeltaAtMs === null) return null;
  const ageMs = performance.now() - lastDeltaAtMs;
  if (ageMs < solidWindowMs) {
    return <Text color={color}>▌</Text>;
  }
  // Pulse: visible on even ticks, blank-but-same-width on odd.
  const visible = tick % 2 === 0;
  return <Text color={color}>{visible ? "▌" : " "}</Text>;
}
