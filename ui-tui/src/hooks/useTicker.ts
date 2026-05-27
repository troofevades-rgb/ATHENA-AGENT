/**
 * useTicker — re-render at a fixed frequency.
 *
 * Returns a monotonically-increasing tick counter that bumps every
 * `intervalMs`. Components subscribe to it for time-driven
 * animations (spinners, pulses, fades) without each computing its
 * own setInterval.
 *
 * Set `paused=true` to halt without unmounting (e.g. pause
 * animation while user is scrolled into history).
 */

import { useEffect, useState } from "react";

export function useTicker(intervalMs: number, paused = false): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (paused) return;
    const t = setInterval(() => setTick((n) => n + 1), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs, paused]);
  return tick;
}
