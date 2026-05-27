/**
 * useStdoutSize — terminal dimensions that actually re-render on
 * resize and on the post-spawn dimension settle.
 *
 * Why this exists:
 *   Ink's ``useStdout()`` returns the raw stdout object. Reading
 *   ``stdout.columns`` from it works for ONE render — but Ink does
 *   not subscribe its consumers to the ``resize`` event, so a
 *   dimension change does not trigger a re-render and components
 *   keep using stale values.
 *
 *   On Windows specifically, ``process.stdout.columns`` can be 0
 *   or a small default for a brief moment between the Node process
 *   starting and the TTY handshake completing. If our layout runs
 *   ONCE during that window the whole banner gets sized for a
 *   non-existent terminal.
 *
 * This hook:
 *   1. Reads the synchronous value on first render (best guess).
 *   2. After mount, re-syncs immediately — picks up the real
 *      dimensions if they settled between render and effect.
 *   3. Subscribes to ``stdout.on('resize')`` so window resizes
 *      reflow the layout live.
 *   4. Cleans up the listener on unmount.
 */

import { useEffect, useState } from "react";
import { useStdout } from "ink";

interface StdoutSize {
  cols: number;
  rows: number;
}

const FALLBACK: StdoutSize = { cols: 100, rows: 30 };

function readSize(stdout: NodeJS.WriteStream | undefined): StdoutSize {
  if (!stdout) return FALLBACK;
  const cols = stdout.columns;
  const rows = stdout.rows;
  // Treat 0 / undefined as "not ready yet" and fall back so the
  // first render doesn't pick layout for a 0-col terminal.
  return {
    cols: cols && cols > 0 ? cols : FALLBACK.cols,
    rows: rows && rows > 0 ? rows : FALLBACK.rows,
  };
}

export function useStdoutSize(): StdoutSize {
  const { stdout } = useStdout();
  const [size, setSize] = useState<StdoutSize>(() => readSize(stdout));

  useEffect(() => {
    if (!stdout) return;
    const onResize = (): void => setSize(readSize(stdout));
    stdout.on("resize", onResize);
    // Post-mount re-sync — catches the spawn-timing case where the
    // TTY reported 0/undefined synchronously but has real values
    // by the time the effect fires.
    onResize();
    return () => {
      stdout.off("resize", onResize);
    };
  }, [stdout]);

  return size;
}
