/**
 * <Transcript> — committed conversation history, rendered through
 * Ink's <Static> so each line is printed exactly ONCE into the
 * terminal's native scrollback. The terminal owns scrolling (mouse
 * wheel, text selection, copy, find) — the app does NOT window the
 * content or track a scroll offset.
 *
 * Consequences of the Static model:
 *   - `lines` is append-only (the reducer never front-trims; Static
 *     tracks emitted items by array index).
 *   - The banner + welcome hints are the FIRST Static item: they print
 *     once at the top and scroll away as the conversation grows
 *     (Claude-Code style). The gateway always sends the banner before
 *     any conversation line, so index 0 stays stable.
 *   - The live streaming message and the input composer live in the
 *     DYNAMIC region below Static (see main.tsx), not here.
 *
 * INVARIANT (kept for simplicity, not required by Static): the reducer
 * splits multi-line content into one TranscriptLine per row at commit
 * time, and renderLine() returns a single <Text>. That keeps the
 * file:line / diff / code per-row classification trivial.
 */

import React from "react";
import { Box, Static, Text } from "ink";

import { Banner } from "./Banner.js";
import { Markdown } from "./Markdown.js";
import type { BannerEvent } from "../transport/protocol.js";
import type { TranscriptLine } from "../state/types.js";

// Matches a "path:line<rest>" prefix on a tool body line (groups:
// leading whitespace, path, line number, rest). Path may not contain a
// colon, so URLs ("https://…") and Windows drive letters ("C:\…") won't
// match — that's fine; we only need relative-path matches to light up.
const FILE_LINE_RE = /^(\s*)([^\s:][^:]*?):(\d+)(.*)$/;

interface Props {
  banner: BannerEvent | null;
  lines: TranscriptLine[];
  termCols: number;
  termRows: number;
}

/** Static item: either a committed transcript line or the one-time
 * welcome block (always index 0 when a banner is present). */
type HistoryItem = TranscriptLine | { key: number; welcome: true };

function isWelcome(i: HistoryItem): i is { key: number; welcome: true } {
  return (i as { welcome?: true }).welcome === true;
}

export function Transcript({
  banner, lines, termCols, termRows,
}: Props): React.JSX.Element {
  const palette = banner?.palette ?? undefined;
  const promptColor = palette?.primary ?? "green";

  // Banner is the first Static item so it prints once and scrolls away.
  // It must precede every line to keep the items array append-only.
  const items: HistoryItem[] = banner
    ? [{ key: -1, welcome: true }, ...lines]
    : lines;

  return (
    <Static items={items}>
      {(item) =>
        isWelcome(item) ? (
          <Welcome
            key="welcome"
            banner={banner as BannerEvent}
            termCols={termCols}
            termRows={termRows}
          />
        ) : (
          renderLine(item, palette, promptColor)
        )
      }
    </Static>
  );
}

/**
 * The welcome block: full banner + getting-started hints. Printed once
 * at the top of the session via Static; scrolls away as history grows.
 */
function Welcome({
  banner, termCols, termRows,
}: {
  banner: BannerEvent;
  termCols: number;
  termRows: number;
}): React.JSX.Element {
  const palette = banner.palette;
  return (
    <Box flexDirection="column">
      <Banner event={banner} termCols={termCols} termRows={Math.max(15, termRows - 12)} />
      <Box flexDirection="column" marginTop={1} marginBottom={1} paddingX={2}>
        <Text color={palette.primary_dim}>try one of these to get started:</Text>
        <Box marginTop={1} flexDirection="column">
          <Text color={palette.accent_dim}>
            {"  "}explain what this project does
          </Text>
          <Text color={palette.accent_dim}>
            {"  "}@ATHENA.md what should I know before touching the agent loop?
          </Text>
          <Text color={palette.accent_dim}>
            {"  "}/plan refactor the X module
          </Text>
          <Text color={palette.accent_dim}>
            {"  "}/help — list every slash command
          </Text>
        </Box>
        <Box marginTop={1} flexDirection="column">
          <Text color={palette.primary_faint}>
            Enter sends · Shift+Enter newline · Tab completes
            {" · "}↑↓ history · Ctrl+R search
          </Text>
          <Text color={palette.primary_faint}>
            Mouse wheel / terminal scrollback to scroll · Esc interrupt · Ctrl+C exit
          </Text>
        </Box>
      </Box>
    </Box>
  );
}

/**
 * Render one transcript line as exactly one terminal row.
 * Never returns a <Box> or multi-child element.
 */
export function renderLine(
  line: TranscriptLine,
  palette: BannerEvent["palette"] | undefined,
  promptColor: string,
): React.JSX.Element {
  if (line.role === "separator") {
    return (
      <Text key={line.key} color={palette?.primary_faint ?? "gray"}>
        {line.content}
      </Text>
    );
  }

  if (line.role === "assistant") {
    // Full block-level markdown — headings, bullet/ordered lists, fenced
    // code, blockquotes, **bold**/*italic*/`code`. The reducer keeps the
    // whole reply in one line, so this renders as a multi-row <Box>,
    // which is fine under <Static>. Indented to match the other roles.
    return (
      <Box key={line.key} paddingLeft={3} flexDirection="column">
        <Markdown
          text={line.content}
          baseColor="white"
          dimColor={palette?.accent_dim}
          accentColor={palette?.accent}
          palette={palette}
        />
      </Box>
    );
  }

  if (line.role === "tool") {
    // Header: "⏺ Tool(args)  dur" — green status dot + dim tool/args.
    if (line.content.startsWith("⏺ ")) {
      const rest = line.content.slice(2);
      return (
        <Text key={line.key}>
          {"   "}
          <Text color={palette?.primary ?? "green"}>⏺</Text>
          {" "}
          <Text color={palette?.accent_dim ?? "yellow"}>{rest}</Text>
        </Text>
      );
    }
    // Body line. Light-touch file:line accenting: ripgrep/Grep emit
    // "path:line:text" (compiler-style output too). Dim the path, accent
    // the :line so references pop — without per-tool coupling. The
    // path-likeness guard (must contain "/", "\", or ".") keeps
    // timestamps ("12:30") and "str | None:" from matching. The "⎿ "
    // branch gutter on the first body line falls inside the dim path
    // span, which is fine.
    const fileLine = line.content.match(FILE_LINE_RE);
    if (fileLine && /[/\\.]/.test(fileLine[2]!)) {
      const [, lead, path, lineNo, rest] = fileLine;
      return (
        <Text key={line.key}>
          {"   "}{lead}
          <Text color={palette?.primary_faint ?? "gray"}>{path}</Text>
          <Text color={palette?.accent_dim ?? "yellow"}>:{lineNo}</Text>
          <Text color={palette?.primary_dim ?? "gray"}>{rest}</Text>
        </Text>
      );
    }
    return (
      <Text key={line.key} color={palette?.primary_dim ?? "gray"}>
        {"   "}{line.content}
      </Text>
    );
  }

  if (line.role === "code") {
    // Fenced code-block line — left gutter + code-style color.
    // Consecutive code lines visually fuse into a block because
    // each gets the same gutter glyph.
    return (
      <Text key={line.key}>
        <Text color={palette?.accent_dim ?? "yellow"}>{"   │ "}</Text>
        <Text color={palette?.accent ?? "cyan"}>{line.content}</Text>
      </Text>
    );
  }

  if (line.role === "diff-add") {
    return (
      <Text key={line.key} color="green">
        {line.content}
      </Text>
    );
  }
  if (line.role === "diff-del") {
    return (
      <Text key={line.key} color="red">
        {line.content}
      </Text>
    );
  }
  if (line.role === "diff-hunk") {
    return (
      <Text key={line.key} color={palette?.accent_dim ?? "yellow"} bold>
        {line.content}
      </Text>
    );
  }
  if (line.role === "diff-file") {
    return (
      <Text key={line.key} color={palette?.primary_faint ?? "gray"} bold>
        {line.content}
      </Text>
    );
  }

  if (line.role === "user") {
    return (
      <Text key={line.key} color={promptColor}>
        {"▸▸ "}{line.content}
      </Text>
    );
  }

  // system
  return (
    <Text key={line.key} color={palette?.primary_dim ?? "gray"}>
      {".  "}{line.content}
    </Text>
  );
}
