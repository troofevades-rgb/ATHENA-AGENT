/**
 * useInputHistory — readline-style up/down history for the composer.
 *
 * Tracks every committed user input. ↑ navigates older, ↓ navigates
 * newer, snapping back to the in-progress draft when you reach the
 * bottom. Standard shell semantics:
 *
 *   - Whatever you've typed (draft) is preserved when you press ↑
 *     from the prompt; ↓ all the way back restores it
 *   - Duplicates of the immediately-previous entry are collapsed
 *     (don't fill history with rapid repeats of the same prompt)
 *   - History is in-memory only — a fresh athena session starts empty
 *
 * Capped at ``maxEntries`` (default 200) so long sessions don't grow
 * unbounded.
 */

import { useCallback, useRef } from "react";

export interface InputHistoryAPI {
  /** Push ``text`` onto history. Called on Enter. Dedupes against
   * the immediately-previous entry. */
  commit(text: string): void;
  /** Step backward (older). Returns the recalled text, or ``null``
   * if there's nothing older. Caller is responsible for setting
   * the editor's buffer + cursor. */
  navigatePrev(currentDraft: string): string | null;
  /** Step forward (newer). Returns the recalled text, or ``""`` to
   * mean "restore the user's saved draft", or ``null`` if already
   * at the bottom (no-op). */
  navigateNext(): string | null;
  /** Forget any in-progress history navigation state. Called when
   * the user does something other than ↑/↓ (e.g. types a character)
   * so the next ↑ resamples the current text as the draft. */
  reset(): void;
  /** Search backward for the most-recent entry containing ``query``
   * (case-insensitive substring). When called repeatedly with the
   * same ``query``, walks to the next-older match. Returns the
   * matched entry, or ``null`` if no match found. */
  searchPrev(query: string, currentDraft: string): string | null;
  /** Cancel an in-progress reverse search and restore the user's
   * stashed draft. Returns the draft. */
  cancelSearch(): string;
  /** Mark the current search match as accepted — clears search
   * state without restoring the draft. */
  acceptSearch(): void;
}

export function useInputHistory(maxEntries = 200): InputHistoryAPI {
  // Oldest → newest. We pop from the end on ↑.
  const history = useRef<string[]>([]);
  // -1 means "not navigating — current buffer is live draft".
  // 0..history.length-1 indexes into history (older = lower index).
  //
  // Held in a ref (not useState) because the hook itself renders
  // nothing — the editor's text changes drive any re-render that's
  // actually needed. Using useState would cause synchronous calls
  // in the keyboard handler (and in tests) to see stale values,
  // because setState updates don't take effect until the next render.
  const cursor = useRef<number>(-1);
  // Saved draft when nav starts — restored when ↓ comes back to the bottom.
  const draft = useRef<string>("");
  // Reverse-search state. ``-1`` means not searching.
  const searchCursor = useRef<number>(-1);
  const searchQuery = useRef<string>("");

  const commit = useCallback((text: string) => {
    if (!text) return;
    const last = history.current[history.current.length - 1];
    if (last !== text) {
      history.current.push(text);
      if (history.current.length > maxEntries) {
        history.current = history.current.slice(-maxEntries);
      }
    }
    cursor.current = -1;
    draft.current = "";
  }, [maxEntries]);

  const navigatePrev = useCallback((currentDraft: string): string | null => {
    const h = history.current;
    if (h.length === 0) return null;
    if (cursor.current === -1) {
      // First press: stash current draft and jump to most-recent entry.
      draft.current = currentDraft;
      cursor.current = h.length - 1;
      return h[cursor.current];
    }
    // Already navigating — step older.
    if (cursor.current === 0) return null;  // already at oldest
    cursor.current -= 1;
    return h[cursor.current];
  }, []);

  const navigateNext = useCallback((): string | null => {
    const h = history.current;
    if (cursor.current === -1) return null;  // not navigating; ↓ is a no-op
    if (cursor.current >= h.length - 1) {
      // Stepping past the newest entry → restore the saved draft.
      cursor.current = -1;
      return draft.current;
    }
    cursor.current += 1;
    return h[cursor.current];
  }, []);

  const reset = useCallback(() => {
    if (cursor.current !== -1) {
      cursor.current = -1;
      draft.current = "";
    }
    if (searchCursor.current !== -1) {
      searchCursor.current = -1;
      searchQuery.current = "";
    }
  }, []);

  const searchPrev = useCallback(
    (query: string, currentDraft: string): string | null => {
      const h = history.current;
      if (h.length === 0 || !query) return null;
      // First call OR query changed → stash draft and start at end.
      // Same query as last call → step from previous match to next older.
      const isContinuation = (
        searchCursor.current !== -1 && searchQuery.current === query
      );
      if (!isContinuation) {
        // Stash the draft ONLY if we're not already navigating (↑
        // already stashed the real draft; the editor's currentDraft
        // is now a recalled history entry, not what the user typed).
        // Without this guard, Ctrl+R-after-↑-then-Esc restores the
        // recalled entry instead of the user's original draft.
        if (cursor.current === -1) {
          draft.current = currentDraft;
        }
        searchQuery.current = query;
        searchCursor.current = h.length;  // walk backwards from past-end
      }
      const q = query.toLowerCase();
      let i = searchCursor.current - 1;
      while (i >= 0) {
        if (h[i].toLowerCase().includes(q)) {
          searchCursor.current = i;
          return h[i];
        }
        i--;
      }
      // No (more) matches; leave cursor at -1 so next call restarts
      // from the end. Don't clear searchQuery — caller can extend it.
      searchCursor.current = 0;
      return null;
    },
    [],
  );

  const cancelSearch = useCallback((): string => {
    const restored = draft.current;
    searchCursor.current = -1;
    searchQuery.current = "";
    draft.current = "";
    return restored;
  }, []);

  const acceptSearch = useCallback((): void => {
    searchCursor.current = -1;
    searchQuery.current = "";
    draft.current = "";
  }, []);

  return {
    commit, navigatePrev, navigateNext, reset,
    searchPrev, cancelSearch, acceptSearch,
  };
}
