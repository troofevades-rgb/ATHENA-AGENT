/**
 * <Markdown> — minimal markdown renderer for assistant transcript.
 *
 * Handles the patterns that actually show up in agent output:
 *   - # / ## / ### headings
 *   - **bold**, *italic*, `inline code`
 *   - ```fenced code blocks``` (no syntax highlighting in this pass —
 *     just monospaced dim text in a border-less block)
 *   - - / * / 1. ordered/unordered lists
 *   - > blockquotes
 *
 * Not a complete CommonMark — tables, images, autolinks, etc. are
 * out of scope (Ink can't render tables in a useful way, and a TUI
 * shouldn't follow links anyway). For richer rendering a future
 * pass can pull in `marked` and walk the AST.
 *
 * The parser is line-based: split on \n, classify each line, then
 * within text/list lines parse inline patterns. Inline parsing
 * uses a single pass with non-overlapping matches to avoid
 * combinatorial explosion.
 */

import React from "react";
import { Box, Text } from "ink";

import type { ThemePalette } from "../transport/protocol.js";
import { tokenizeCode, type CodeTokenKind } from "../stream/syntaxHighlight.js";

interface Props {
  text: string;
  /** Color the assistant text uses by default. */
  baseColor?: string;
  /** Dim color for code blocks, blockquotes, etc. */
  dimColor?: string;
  /** Accent color for headings + emphasis. */
  accentColor?: string;
  /** When provided, fenced code blocks are syntax-highlighted using
   * these colors; without it they render flat in dimColor. */
  palette?: ThemePalette;
}

/** Map a code token kind to a palette color (undefined = inherit the
 * surrounding dim code color, used for plain tokens). */
function codeColor(kind: CodeTokenKind, palette: ThemePalette): string | undefined {
  switch (kind) {
    case "keyword": return palette.accent;
    case "string": return palette.primary;
    case "comment": return palette.primary_faint;
    case "number": return palette.accent_dim;
    case "function": return palette.primary_dim;
    default: return undefined;
  }
}

interface Block {
  kind: "heading" | "text" | "code" | "list" | "quote" | "blank";
  level?: number;       // heading level
  text: string;
  ordered?: boolean;    // for list items
  index?: number;       // for ordered list items
}

function parseBlocks(src: string): Block[] {
  const lines = src.split("\n");
  const blocks: Block[] = [];
  let inCode = false;
  let codeAccum: string[] = [];

  for (const raw of lines) {
    // Fenced code blocks (toggle on ```).
    if (raw.trimStart().startsWith("\`\`\`")) {
      if (inCode) {
        blocks.push({ kind: "code", text: codeAccum.join("\n") });
        codeAccum = [];
        inCode = false;
      } else {
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeAccum.push(raw);
      continue;
    }
    if (raw.trim() === "") {
      blocks.push({ kind: "blank", text: "" });
      continue;
    }
    // Headings: # foo, ## foo, ### foo
    const h = raw.match(/^(#{1,3})\s+(.+)$/);
    if (h) {
      const hashes = h[1] ?? "";
      const body = h[2] ?? "";
      blocks.push({ kind: "heading", level: hashes.length, text: body });
      continue;
    }
    // Blockquote
    if (raw.startsWith("> ")) {
      blocks.push({ kind: "quote", text: raw.slice(2) });
      continue;
    }
    // Unordered list
    const ul = raw.match(/^[ ]{0,3}[-*]\s+(.+)$/);
    if (ul) {
      blocks.push({ kind: "list", text: ul[1] ?? "", ordered: false });
      continue;
    }
    // Ordered list
    const ol = raw.match(/^[ ]{0,3}(\d+)\.\s+(.+)$/);
    if (ol) {
      const idxStr = ol[1] ?? "0";
      const body = ol[2] ?? "";
      blocks.push({
        kind: "list", text: body, ordered: true, index: parseInt(idxStr, 10),
      });
      continue;
    }
    // Plain text line
    blocks.push({ kind: "text", text: raw });
  }
  // Unclosed code fence: render what we have so we don't drop content.
  if (inCode && codeAccum.length > 0) {
    blocks.push({ kind: "code", text: codeAccum.join("\n") });
  }
  return blocks;
}

/** Tokenize a string into inline spans: bold, italic, code, plain. */
type Span = { kind: "plain" | "bold" | "italic" | "code"; text: string };

function parseInline(src: string): Span[] {
  // Greedy left-to-right scan. Patterns in priority order:
  //   `code` first (its contents shouldn't be re-interpreted)
  //   **bold**
  //   *italic*
  // A simpler design than a full parser, sufficient for chat output.
  const spans: Span[] = [];
  let rest = src;
  const patterns: Array<[Span["kind"], RegExp]> = [
    ["code", /^\`([^\`]+)\`/],
    ["bold", /^\*\*([^*]+)\*\*/],
    ["italic", /^\*([^*]+)\*/],
  ];
  while (rest.length > 0) {
    let matched = false;
    for (const [kind, re] of patterns) {
      const m = rest.match(re);
      if (m) {
        spans.push({ kind, text: m[1] ?? "" });
        rest = rest.slice(m[0].length);
        matched = true;
        break;
      }
    }
    if (matched) continue;
    // No pattern matched at index 0 — find next pattern's start to chunk plain text.
    const nextSpecial = findNextSpecial(rest);
    if (nextSpecial === -1) {
      spans.push({ kind: "plain", text: rest });
      break;
    }
    spans.push({ kind: "plain", text: rest.slice(0, nextSpecial) });
    rest = rest.slice(nextSpecial);
  }
  return spans;
}

function findNextSpecial(s: string): number {
  // Find the earliest occurrence of `, **, or * that could start a span.
  const idxs = [
    s.indexOf("\`"),
    s.indexOf("**"),
    s.indexOf("*"),
  ].filter((i) => i !== -1);
  if (idxs.length === 0) return -1;
  return Math.min(...idxs);
}

function renderSpans(
  spans: Span[],
  keyPrefix: string,
  opts: { dimColor?: string; accentColor?: string },
): React.ReactNode {
  return spans.map((s, i) => {
    const key = `${keyPrefix}-${i}`;
    if (s.kind === "bold") return <Text key={key} bold color={opts.accentColor}>{s.text}</Text>;
    if (s.kind === "italic") return <Text key={key} italic>{s.text}</Text>;
    if (s.kind === "code") return <Text key={key} color={opts.dimColor ?? "cyan"}>{s.text}</Text>;
    return <Text key={key}>{s.text}</Text>;
  });
}

export function Markdown({
  text, baseColor, dimColor, accentColor, palette,
}: Props): React.JSX.Element {
  const blocks = parseBlocks(text);
  return (
    <Box flexDirection="column">
      {blocks.map((b, i) => {
        const k = `b${i}`;
        if (b.kind === "blank") {
          return <Text key={k}> </Text>;
        }
        if (b.kind === "heading") {
          const sizeMark = "#".repeat(b.level ?? 1);
          return (
            <Text key={k} bold color={accentColor}>
              {sizeMark} {b.text}
            </Text>
          );
        }
        if (b.kind === "code") {
          return (
            <Box key={k} flexDirection="column" marginY={0}>
              {b.text.split("\n").map((ln, j) => (
                <Text key={`${k}-${j}`} color={dimColor ?? "cyan"}>
                  {"  "}
                  {palette
                    ? tokenizeCode(ln).map((t, ti) => (
                        <Text
                          key={ti}
                          color={codeColor(t.kind, palette)}
                          bold={t.kind === "keyword"}
                        >
                          {t.text}
                        </Text>
                      ))
                    : ln}
                </Text>
              ))}
            </Box>
          );
        }
        if (b.kind === "quote") {
          return (
            <Text key={k} dimColor italic color={dimColor}>
              │ {b.text}
            </Text>
          );
        }
        if (b.kind === "list") {
          const bullet = b.ordered ? `${b.index}.` : "•";
          return (
            <Text key={k} color={baseColor}>
              {"  "}{bullet} {renderSpans(parseInline(b.text), k, { dimColor, accentColor })}
            </Text>
          );
        }
        // Plain text line
        return (
          <Text key={k} color={baseColor}>
            {renderSpans(parseInline(b.text), k, { dimColor, accentColor })}
          </Text>
        );
      })}
    </Box>
  );
}
