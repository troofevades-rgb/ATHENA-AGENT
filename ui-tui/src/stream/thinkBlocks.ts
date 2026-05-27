/**
 * Reasoning-model output filtering.
 *
 * Local models (qwen 2.5/3, deepseek-r1, etc.) emit chain-of-
 * thought wrapped in ``<think>...</think>`` blocks. The model
 * expects callers to discard the thought trace before showing
 * the user. Without filtering, the TUI shows literal tags +
 * the full reasoning stream — which looks buggy.
 *
 * This module collapses those blocks into a single dim marker
 * so the user knows the model is reasoning but doesn't see
 * the trace itself.
 *
 *   open think, no close yet  → "· thinking…" (and suppress
 *                                rest of buffer until close)
 *   complete think block      → "· (thought)" past-tense marker
 *   no think tags             → text unchanged
 *
 * Two entry points:
 *   - ``filterThinkBlocks(text)`` — one-shot, full-buffer scan.
 *     For tests and committed-message rendering.
 *   - ``appendFilter(state, chunk)`` — INCREMENTAL, used by the
 *     stream.delta reducer. Each call is O(chunk_size); previous
 *     versions re-filtered the full accumulated stream on every
 *     delta (O(N²)), OOM'ing the Node subprocess at ~4 GB after
 *     a few minutes of OSINT-style activity.
 */

const OPEN_TAG = "<think>";
const CLOSE_TAG = "</think>";
const LIVE_MARKER = "· thinking…";
const DONE_MARKER = "· (thought)";

// =====================================================================
//  One-shot filter — preserves the original behavior for tests and
//  for re-rendering committed (non-streaming) text.
// =====================================================================

export function filterThinkBlocks(text: string): string {
  let out = "";
  let pos = 0;
  while (true) {
    const openIdx = text.indexOf(OPEN_TAG, pos);
    if (openIdx === -1) {
      out += text.slice(pos);
      break;
    }
    out += text.slice(pos, openIdx);
    const closeIdx = text.indexOf(CLOSE_TAG, openIdx);
    if (closeIdx === -1) {
      out += LIVE_MARKER;
      break;
    }
    out += DONE_MARKER;
    pos = closeIdx + CLOSE_TAG.length;
  }
  // Defense in depth: strip any orphan tags.
  return out.replace(/<\/?think>/g, "");
}

// =====================================================================
//  Incremental filter — called once per stream.delta.
// =====================================================================

export interface ThinkFilterState {
  /** Are we currently inside an unmatched <think>? */
  readonly inThink: boolean;
  /** Suffix chars that could be the prefix of a tag we care about,
   * held back from output so a partial match split across two
   * deltas resolves correctly on the next call. Bounded to
   * ``CLOSE_TAG.length - 1 == 7`` chars. */
  readonly tail: string;
  /** Length of the live "· thinking…" marker currently held at the
   * end of the consumer's streaming buffer — set when we enter a
   * block, cleared (via popLen) when the block closes. */
  readonly liveMarkerLen: number;
}

export const initialThinkFilterState: ThinkFilterState = {
  inThink: false,
  tail: "",
  liveMarkerLen: 0,
};

export interface FilterResult {
  readonly state: ThinkFilterState;
  /** Number of characters to POP off the end of the consumer's
   * existing streaming buffer before appending ``append``. Used
   * to swap the live "thinking…" marker for "(thought)" when a
   * block closes. */
  readonly popLen: number;
  /** Characters to append to the streaming buffer. */
  readonly append: string;
}

/**
 * How many chars at the end of ``s.slice(fromPos)`` match a NON-FULL
 * prefix of ``tag``? Used to decide which suffix chars must be held
 * back as ``tail`` to resolve a tag straddling the next delta.
 *
 * Returns 0 when there's no partial match — meaning the whole text
 * (from fromPos onward) is safe to emit.
 */
function partialPrefixSuffix(s: string, fromPos: number, tag: string): number {
  const slice = s.slice(fromPos);
  const max = Math.min(slice.length, tag.length - 1);
  for (let k = max; k > 0; k--) {
    if (slice.endsWith(tag.slice(0, k))) return k;
  }
  return 0;
}

export function appendFilter(
  prev: ThinkFilterState,
  chunk: string,
): FilterResult {
  // Prepend the held tail so partial tags from prior call resolve.
  const text = prev.tail + chunk;
  let pos = 0;
  let inThink = prev.inThink;
  let append = "";
  // `popLen` ONLY refers to chars in the CONSUMER's existing
  // streaming buffer (from prior deltas). It must NOT be used to
  // reflect a LIVE_MARKER we add to `append` in THIS call — the
  // consumer pops from its buffer, not from our append, so popping
  // for a same-call marker would eat real content.
  //
  // To track this correctly we distinguish:
  //   priorLiveMarkerLen — live marker is sitting in the consumer's
  //                        buffer from a previous delta. Pop it on close.
  //   appendLiveMarker  — live marker is at the end of THIS call's
  //                        append. Strip it from append on close
  //                        (no popLen needed; never reached the buffer).
  let priorLiveMarkerLen = prev.liveMarkerLen;
  let appendLiveMarkerLen = 0;
  let popLen = 0;

  while (pos < text.length) {
    if (inThink) {
      const closeIdx = text.indexOf(CLOSE_TAG, pos);
      if (closeIdx === -1) {
        // No close tag yet. Hold ONLY chars that could be a
        // partial CLOSE_TAG prefix — everything else inside the
        // block is suppressed anyway (we're in think mode).
        const tailLen = partialPrefixSuffix(text, pos, CLOSE_TAG);
        const tailStart = text.length - tailLen;
        // Live marker survival: either it's already in the consumer
        // buffer (priorLiveMarkerLen) or in our append
        // (appendLiveMarkerLen). Either way the consumer will see
        // it after this round, so report whichever is non-zero.
        const liveMarkerLen = priorLiveMarkerLen > 0
          ? priorLiveMarkerLen
          : appendLiveMarkerLen;
        return {
          state: { inThink: true, tail: text.slice(tailStart), liveMarkerLen },
          popLen,
          append,
        };
      }
      // Block closed. Swap live marker → done marker.
      if (priorLiveMarkerLen > 0) {
        // Marker is in the consumer's buffer — instruct it to pop.
        popLen += priorLiveMarkerLen;
        priorLiveMarkerLen = 0;
      } else if (appendLiveMarkerLen > 0) {
        // Marker is at the end of OUR append — just strip it
        // locally; the consumer's buffer was never modified.
        append = append.slice(0, -appendLiveMarkerLen);
        appendLiveMarkerLen = 0;
      }
      append += DONE_MARKER;
      inThink = false;
      pos = closeIdx + CLOSE_TAG.length;
    } else {
      const openIdx = text.indexOf(OPEN_TAG, pos);
      if (openIdx === -1) {
        // No open tag. Emit everything except chars that could be
        // a partial OPEN_TAG prefix at the very end.
        const tailLen = partialPrefixSuffix(text, pos, OPEN_TAG);
        const tailStart = text.length - tailLen;
        append += text.slice(pos, tailStart);
        return {
          state: { inThink: false, tail: text.slice(tailStart), liveMarkerLen: 0 },
          popLen,
          append,
        };
      }
      append += text.slice(pos, openIdx);
      // Enter block — emit the live marker so user sees activity.
      append += LIVE_MARKER;
      appendLiveMarkerLen = LIVE_MARKER.length;
      inThink = true;
      pos = openIdx + OPEN_TAG.length;
    }
  }
  // End of chunk. If we're still inThink, the live marker is now
  // somewhere — either in the consumer's buffer (priorLiveMarkerLen)
  // or at the end of our append (appendLiveMarkerLen). Report
  // whichever applies so the next call can pop correctly when
  // </think> arrives.
  const liveMarkerLen = inThink
    ? (priorLiveMarkerLen > 0 ? priorLiveMarkerLen : appendLiveMarkerLen)
    : 0;
  return {
    state: { inThink, tail: "", liveMarkerLen },
    popLen,
    append,
  };
}
