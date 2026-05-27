/**
 * useMouseWheel — terminal mouse wheel scrolling.
 *
 * Patches stdin.read() to strip SGR mouse escape sequences before
 * Ink's App component sees them. Wheel events (button bit 6 set)
 * trigger scroll callbacks. Click/drag events are silently consumed.
 *
 * This mirrors Hermes Agent's approach (they fork Ink's tokenizer;
 * we patch stdin.read() in front of stock Ink for the same effect).
 *
 * ConPTY note: default to disabled on Windows — ConPTY injects
 * phantom mouse events. Caller passes enabled=false on win32.
 */

import { useEffect, useRef } from "react";

const ENABLE = "\x1b[?1000h\x1b[?1006h";
const DISABLE = "\x1b[?1000l\x1b[?1006l";

// SGR mouse: ESC [ < Btn ; Col ; Row M/m
const SGR_RE = /\x1b\[<(\d+);\d+;\d+[Mm]/g;

export function useMouseWheel(
  onScroll: (delta: number) => void,
  enabled: boolean = true,
): void {
  const scrollRef = useRef(onScroll);
  scrollRef.current = onScroll;

  useEffect(() => {
    if (!enabled) return;

    const stdin = process.stdin as any;
    if (!stdin.isTTY) return;

    const origRead = stdin.read.bind(stdin);

    stdin.read = function patchedRead(size?: number): string | Buffer | null {
      const chunk = origRead(size);
      if (chunk === null) return null;

      const str = typeof chunk === "string" ? chunk : chunk.toString("utf-8");

      // Extract wheel events
      let m: RegExpExecArray | null;
      SGR_RE.lastIndex = 0;
      while ((m = SGR_RE.exec(str)) !== null) {
        const btn = parseInt(m[1]!, 10);
        if ((btn & 0x43) === 0x40) scrollRef.current(3);       // wheel up
        else if ((btn & 0x43) === 0x41) scrollRef.current(-3);  // wheel down
      }

      // Strip all mouse sequences
      const cleaned = str.replace(SGR_RE, "");
      if (cleaned.length === 0) return origRead(0) ?? null;
      return cleaned;
    };

    process.stdout.write(ENABLE);

    return () => {
      process.stdout.write(DISABLE);
      stdin.read = origRead;
    };
  }, [enabled]);
}
