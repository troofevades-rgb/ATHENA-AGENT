/**
 * useLineEditor — the readline-style input model.
 *
 * Extracted from main.tsx so the keyboard model is testable in
 * isolation and reusable (the multi-line composer, the search
 * box, the slash-command palette will all want this someday).
 *
 * Returns the current `{text, cursor}` plus dispatch handlers.
 * Owns no React state directly — uses useState internally and
 * exposes operations. Composer wraps it with the actual Ink
 * useInput binding.
 */

import { useCallback, useEffect, useState } from "react";

export interface LineEditorState {
  text: string;
  cursor: number;
}

export interface LineEditorAPI {
  text: string;
  cursor: number;
  /** Insert `char` (or multi-char paste) at the current cursor. */
  insert(char: string): void;
  /** Delete the character immediately LEFT of the cursor. */
  backspace(): void;
  /** Delete the character AT the cursor (forward delete). */
  forwardDelete(): void;
  /** Move the cursor one column left (no-op at column 0). */
  moveLeft(): void;
  /** Move the cursor one column right (no-op at end of line). */
  moveRight(): void;
  /** Jump to column 0 (Home / Ctrl-A). */
  toStart(): void;
  /** Jump to end of line (End / Ctrl-E). */
  toEnd(): void;
  /** Clear from cursor to start (Ctrl-U). */
  killToStart(): void;
  /** Clear from cursor to end (Ctrl-K). */
  killToEnd(): void;
  /** Delete the word left of the cursor (Ctrl-W). */
  killWordLeft(): void;
  /** Empty the buffer (e.g. after submit). */
  clear(): void;
}

export function useLineEditor(): LineEditorAPI {
  const [text, setText] = useState("");
  const [cursor, setCursor] = useState(0);

  // Clamp cursor when text shrinks (e.g. submit clears it).
  useEffect(() => {
    if (cursor > text.length) setCursor(text.length);
  }, [text, cursor]);

  const insert = useCallback((char: string) => {
    setText((s) => s.slice(0, cursor) + char + s.slice(cursor));
    setCursor((p) => p + char.length);
  }, [cursor]);

  const backspace = useCallback(() => {
    if (cursor === 0) return;
    setText((s) => s.slice(0, cursor - 1) + s.slice(cursor));
    setCursor((p) => p - 1);
  }, [cursor]);

  const forwardDelete = useCallback(() => {
    setText((s) => s.slice(0, cursor) + s.slice(cursor + 1));
  }, [cursor]);

  const moveLeft = useCallback(() => {
    setCursor((p) => Math.max(0, p - 1));
  }, []);

  const moveRight = useCallback(() => {
    setCursor((p) => Math.min(text.length, p + 1));
  }, [text.length]);

  const toStart = useCallback(() => setCursor(0), []);
  const toEnd = useCallback(() => setCursor(text.length), [text.length]);

  const killToStart = useCallback(() => {
    setText((s) => s.slice(cursor));
    setCursor(0);
  }, [cursor]);

  const killToEnd = useCallback(() => {
    setText((s) => s.slice(0, cursor));
  }, [cursor]);

  const killWordLeft = useCallback(() => {
    setText((s) => {
      const left = s.slice(0, cursor);
      const right = s.slice(cursor);
      const trimmed = left.replace(/\s*\S+\s*$/, "");
      setCursor(trimmed.length);
      return trimmed + right;
    });
  }, [cursor]);

  const clear = useCallback(() => {
    setText("");
    setCursor(0);
  }, []);

  return {
    text, cursor, insert, backspace, forwardDelete,
    moveLeft, moveRight, toStart, toEnd,
    killToStart, killToEnd, killWordLeft, clear,
  };
}
