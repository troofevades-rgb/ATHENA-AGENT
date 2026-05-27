/**
 * useBracketedPaste — collapse multi-line pastes into single events.
 *
 * Without this, pasting a 50-line snippet into the composer fires
 * useInput 50+ times. Each press of `/` mid-paste opens the slash
 * popup, each newline submits the prompt prematurely, and the
 * whole experience is glitchy and slow.
 *
 * With bracketed paste mode enabled, terminals wrap pasted content
 * in ``\e[200~`` ... ``\e[201~`` markers. We intercept those at
 * the stdin layer (same pattern as useMouseWheel), buffer the
 * content between the markers, and deliver it as ONE callback
 * after the closing marker arrives. Ink's useInput never sees the
 * paste content, so no per-keystroke processing happens.
 *
 * Pastes that span multiple chunks (a 1 MB paste arrives in
 * several reads from stdin) are reassembled across read() calls.
 */

import { useEffect, useRef } from "react";

const ENABLE = "\x1b[?2004h";
const DISABLE = "\x1b[?2004l";
const START_MARKER = "\x1b[200~";
const END_MARKER = "\x1b[201~";


export function useBracketedPaste(
  onPaste: (content: string) => void,
  enabled: boolean = true,
): void {
  const onPasteRef = useRef(onPaste);
  onPasteRef.current = onPaste;

  useEffect(() => {
    if (!enabled) return;

    const stdin = process.stdin as any;
    if (!stdin.isTTY) return;

    const origRead = stdin.read.bind(stdin);
    // Buffer state for paste content that spans multiple read() chunks.
    let pasteBuffer = "";
    let inPaste = false;

    stdin.read = function patchedRead(size?: number): string | Buffer | null {
      const chunk = origRead(size);
      if (chunk === null) return null;
      const raw = typeof chunk === "string" ? chunk : chunk.toString("utf-8");

      // Walk the chunk; whenever we cross a paste boundary, deliver
      // the accumulated content via callback. Outside paste mode,
      // pass bytes through unchanged.
      let out = "";
      let i = 0;
      while (i < raw.length) {
        if (!inPaste) {
          const startIdx = raw.indexOf(START_MARKER, i);
          if (startIdx === -1) {
            // No paste in remaining chunk — flush rest as keystrokes
            out += raw.slice(i);
            break;
          }
          out += raw.slice(i, startIdx);
          i = startIdx + START_MARKER.length;
          inPaste = true;
          pasteBuffer = "";
        } else {
          const endIdx = raw.indexOf(END_MARKER, i);
          if (endIdx === -1) {
            // Paste content continues into next chunk
            pasteBuffer += raw.slice(i);
            break;
          }
          pasteBuffer += raw.slice(i, endIdx);
          i = endIdx + END_MARKER.length;
          inPaste = false;
          // Deliver as one event
          try {
            onPasteRef.current(pasteBuffer);
          } catch (err) {
            // Never let a paste handler crash stdin processing
            // eslint-disable-next-line no-console
            console.error("paste handler threw:", err);
          }
          pasteBuffer = "";
        }
      }

      if (out.length === 0) {
        // Returning empty string would confuse Ink's read loop;
        // call origRead(0) to give it the standard "no data right
        // now" signal.
        return origRead(0) ?? null;
      }
      return out;
    };

    process.stdout.write(ENABLE);

    return () => {
      process.stdout.write(DISABLE);
      stdin.read = origRead;
      pasteBuffer = "";
      inPaste = false;
    };
  }, [enabled]);
}
