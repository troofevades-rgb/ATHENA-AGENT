/**
 * useTokenRate — rolling token-per-second tracker.
 *
 * Watches a stream of (timestamp, totalTokens) samples and returns
 * a sparkline-ready array of tps values for the last `windowSec`
 * seconds. Bucketed at ~1Hz to keep the sparkline stable across
 * rapid event bursts.
 *
 * The sparkline glyph width is fixed (`buckets`); empty buckets
 * render as the lowest bar so the line is always present once
 * any activity has been seen.
 */

import { useEffect, useRef, useState } from "react";

export interface TokenRateState {
  /** Current tps over the most-recent ~5s. */
  current: number;
  /** Per-bucket tps for the rolling window, oldest → newest. */
  history: number[];
}

export function useTokenRate(
  totalTokens: number,
  options: { buckets?: number; windowSec?: number } = {},
): TokenRateState {
  const buckets = options.buckets ?? 16;
  const windowSec = options.windowSec ?? 30;
  const bucketSec = windowSec / buckets;
  // Per-bucket [bucketStartMs, tokensAtStart] tuples. We push a
  // new entry every `bucketSec`; ages out older than windowSec.
  const samples = useRef<Array<[number, number]>>([]);
  const [state, setState] = useState<TokenRateState>({
    current: 0,
    history: new Array(buckets).fill(0),
  });

  useEffect(() => {
    const now = performance.now();
    const oldestAllowed = now - windowSec * 1000;
    // Append the latest sample.
    samples.current.push([now, totalTokens]);
    // Drop samples older than the window.
    samples.current = samples.current.filter(([t]) => t >= oldestAllowed);
    if (samples.current.length < 2) {
      return;
    }
    // Bucket: walk samples, compute delta per ~bucketSec slot.
    const history: number[] = [];
    const windowStartMs = now - windowSec * 1000;
    for (let i = 0; i < buckets; i++) {
      const bStart = windowStartMs + i * bucketSec * 1000;
      const bEnd = bStart + bucketSec * 1000;
      const inBucket = samples.current.filter(([t]) => t >= bStart && t < bEnd);
      const first = inBucket[0];
      const last = inBucket[inBucket.length - 1];
      if (inBucket.length < 2 || !first || !last) {
        history.push(0);
        continue;
      }
      const tokensDelta = last[1] - first[1];
      const dtSec = (last[0] - first[0]) / 1000;
      history.push(dtSec > 0 ? tokensDelta / dtSec : 0);
    }
    // Current tps = average of the most-recent 5s.
    const tailStart = now - 5000;
    const tail = samples.current.filter(([t]) => t >= tailStart);
    let current = 0;
    const tailFirst = tail[0];
    const tailLast = tail[tail.length - 1];
    if (tail.length >= 2 && tailFirst && tailLast) {
      const tokensDelta = tailLast[1] - tailFirst[1];
      const dtSec = (tailLast[0] - tailFirst[0]) / 1000;
      current = dtSec > 0 ? tokensDelta / dtSec : 0;
    }
    setState({ current, history });
  }, [totalTokens, buckets, windowSec, bucketSec]);

  return state;
}

/** Render a tps history array as a unicode sparkline string. */
export function renderSparkline(history: number[]): string {
  const bars = "▁▂▃▄▅▆▇█";
  const max = Math.max(...history, 1);
  return history
    .map((v) => bars[Math.min(bars.length - 1, Math.floor((v / max) * bars.length))])
    .join("");
}
