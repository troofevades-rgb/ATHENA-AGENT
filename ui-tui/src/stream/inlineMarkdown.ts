/**
 * Inline markdown parser for the transcript.
 *
 * Splits one line of text into styled segments without breaking the
 * one-row-per-line invariant. Block-level markdown (headers,
 * fences, lists) is NOT handled here — that would require multi-row
 * rendering and conflict with the windowing math.
 *
 * Tokens recognized, in priority order at each position:
 *   - ``...``   — inline code
 *   - `**...**`            — bold
 *   - `*...*`              — italic
 *   - `http(s)://...`      — URL (whitespace-bounded)
 *
 * Conservative on ambiguity:
 *   - An unterminated `**` or `*` falls through to literal text
 *   - A backtick with no closer falls through
 *   - Empty tokens (`**bold-but-empty**` → '') are dropped to avoid
 *     emitting zero-width styled spans
 */

export interface InlineSegment {
  text: string;
  bold?: boolean;
  italic?: boolean;
  code?: boolean;
  url?: boolean;
}


export function parseInline(text: string): InlineSegment[] {
  if (!text) return [];
  const out: InlineSegment[] = [];
  let i = 0;
  let buf = "";

  const flush = (): void => {
    if (buf) {
      out.push({ text: buf });
      buf = "";
    }
  };
  const push = (seg: InlineSegment): void => {
    if (seg.text) out.push(seg);
  };

  while (i < text.length) {
    const ch = text[i];

    // Inline code: `...` — most literal, try first
    if (ch === "`") {
      const end = text.indexOf("`", i + 1);
      if (end > i) {
        flush();
        push({ text: text.slice(i + 1, end), code: true });
        i = end + 1;
        continue;
      }
    }

    // Bold: **...** — must be checked before italic (single *)
    if (ch === "*" && text[i + 1] === "*") {
      const end = text.indexOf("**", i + 2);
      if (end > i + 1) {
        flush();
        push({ text: text.slice(i + 2, end), bold: true });
        i = end + 2;
        continue;
      }
      // Unterminated **: emit both stars literally and skip past
      // them. Otherwise the italic case below would consume the
      // second * and produce a phantom italic span.
      buf += "**";
      i += 2;
      continue;
    }

    // Italic: *...* — guard against this being the LEADING * of an
    // unterminated bold (rejected above with a literal emit) or the
    // OPENING * of a yet-untraversed **, both of which would produce
    // a phantom empty italic.
    if (ch === "*") {
      const end = text.indexOf("*", i + 1);
      if (end > i && text[end + 1] !== "*" && text[end - 1] !== "*") {
        flush();
        push({ text: text.slice(i + 1, end), italic: true });
        i = end + 1;
        continue;
      }
    }

    // URL: http(s)://...  (whitespace- or end-bounded)
    if (
      text.startsWith("http://", i) || text.startsWith("https://", i)
    ) {
      let end = i;
      while (end < text.length && !/\s/.test(text[end])) end++;
      // Strip common trailing punctuation that's almost never part
      // of the URL: ., ,, ), ;, :, ? !
      while (end > i + 8 && /[.,);:?!]$/.test(text[end - 1])) end--;
      flush();
      push({ text: text.slice(i, end), url: true });
      i = end;
      continue;
    }

    buf += ch;
    i++;
  }
  flush();
  return out;
}
