/**
 * <Transcript> — the scrolling content region.
 *
 * INVARIANT: every TranscriptLine renders as exactly ONE terminal
 * row. The reducer splits multi-line content at commit time.
 * renderLine() returns a single <Text> — never a <Box> with
 * children that could be taller than one row. This makes the
 * windowing math (visibleBudget = terminal rows available)
 * trivially correct and prevents the layout collisions that
 * happened when multi-row elements overflowed the viewport.
 */

import React from "react";
import { Box, Text } from "ink";

import { Banner } from "./Banner.js";
import { Nameplate } from "./Nameplate.js";
import { PulsingCursor } from "./PulsingCursor.js";
import { parseInline } from "../stream/inlineMarkdown.js";
import type { BannerEvent } from "../transport/protocol.js";
import type { TranscriptLine } from "../state/types.js";

interface Props {
  banner: BannerEvent | null;
  lines: TranscriptLine[];
  streaming: string;
  streamId: string | null;
  scrollOffset: number;
  visibleBudget: number;
  termCols: number;
  termRows: number;
  lastDeltaAtMs?: number | null;
}

export function Transcript({
  banner, lines, streaming, streamId,
  scrollOffset, visibleBudget, termCols, termRows,
  lastDeltaAtMs = null,
}: Props): React.JSX.Element {
  const palette = banner?.palette ?? undefined;
  const promptColor = palette?.primary ?? "green";
  const hasConversation = lines.length > 0 || streamId !== null;
  const headerHeight = hasConversation ? 1 : Math.max(15, termRows - 12);

  // Split the streaming buffer into rows so it doesn't overflow
  // the viewport (same invariant as committed lines: 1 entry = 1 row).
  // Trim trailing empty rows that ``"".split("\n")`` produces — without
  // this, a freshly-opened stream with no content yet renders an empty
  // row + floating PulsingCursor (visible as a stray ▌ above the
  // composer when the model stalls between stream.start and the first
  // delta).
  const rawRows = (!scrollOffset && streamId !== null && streaming)
    ? streaming.split("\n")
    : [];
  let trimEnd = rawRows.length;
  while (trimEnd > 0 && rawRows[trimEnd - 1] === "") trimEnd--;
  const streamingRows = rawRows.slice(0, trimEnd);
  // Reserve rows for the streaming buffer so committed lines
  // don't fight with live text for viewport space.
  const streamReserve = streamingRows.length > 0
    ? Math.min(streamingRows.length + 1, Math.floor(visibleBudget / 2))
    : 0;
  const committedBudget = visibleBudget - streamReserve;

  const windowEnd = Math.max(0, lines.length - scrollOffset);
  const windowStart = Math.max(0, windowEnd - committedBudget);
  const visibleLines = hasConversation
    ? lines.slice(windowStart, windowEnd)
    : [];
  const moreBelow = scrollOffset > 0 ? scrollOffset : 0;
  const moreAbove = Math.max(0, windowStart);
  const scrolledUp = scrollOffset > 0;

  // Show only the tail of streaming text that fits in the reserve
  const streamTail = streamReserve > 0
    ? streamingRows.slice(-streamReserve)
    : [];

  if (!hasConversation) {
    return (
      <Box flexDirection="column" flexGrow={1} overflow="hidden">
        {banner && palette ? (
          <Banner event={banner} termCols={termCols} termRows={headerHeight} />
        ) : (
          <Text dimColor>connecting to gateway…</Text>
        )}
        <Box flexGrow={1} />
        {banner && palette && (
          <Box flexDirection="column" marginBottom={1} paddingX={2}>
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
            <Box marginTop={1} flexDirection="column" alignItems="center">
              <Text color={palette.primary_faint}>
                Enter sends · Shift+Enter newline · Tab completes
                {" · "}↑↓ history · Ctrl+R search
              </Text>
              <Text color={palette.primary_faint}>
                Shift+↑↓ or PageUp/Dn to scroll · Esc interrupt · Ctrl+C exit
              </Text>
            </Box>
          </Box>
        )}
      </Box>
    );
  }

  return (
    <Box flexDirection="column" flexGrow={1} overflow="hidden">
      {banner && palette && <Nameplate banner={banner} palette={palette} />}
      <Box flexGrow={1} />
      {moreAbove > 0 && (
        <Text color={palette?.primary_faint ?? "gray"} dimColor>
          ↑ {moreAbove} earlier line{moreAbove === 1 ? "" : "s"}
          {scrollOffset === 0 ? " — Shift+↑ or PageUp to scroll" : ""}
        </Text>
      )}
      {visibleLines.map((line) => renderLine(line, palette, promptColor))}
      {streamTail.length > 0 && (
        <>
          {streamTail.map((row, i) => (
            <Text key={`s${i}`} color="white">
              {i === 0 ? "" : "   "}{i === 0 ? "" : ""}{row}
            </Text>
          ))}
          <PulsingCursor lastDeltaAtMs={lastDeltaAtMs} color="white" />
        </>
      )}
      {moreBelow > 0 && (
        <Text color={palette?.accent ?? "yellow"} dimColor>
          ↓ {moreBelow} newer line{moreBelow === 1 ? "" : "s"} —
          press Esc to jump to bottom
        </Text>
      )}
    </Box>
  );
}

/**
 * Render one transcript line as exactly one terminal row.
 * Never returns a <Box> or multi-child element.
 */
function renderLine(
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
    // Inline markdown: **bold**, *italic*, `code`, URLs — split the
    // line into styled spans without breaking the one-row invariant.
    // Block-level markdown (headers, fences, lists) is NOT handled
    // because it would require multi-row layout.
    const segments = parseInline(line.content);
    return (
      <Text key={line.key} color="white">
        {"   "}
        {segments.map((s, i) => {
          const segKey = `${line.key}-${i}`;
          if (s.code) {
            return (
              <Text key={segKey} color={palette?.accent_dim ?? "yellow"}>
                {s.text}
              </Text>
            );
          }
          if (s.url) {
            return (
              <Text key={segKey} color={palette?.accent ?? "cyan"} underline>
                {s.text}
              </Text>
            );
          }
          return (
            <Text
              key={segKey}
              bold={s.bold ?? false}
              italic={s.italic ?? false}
            >
              {s.text}
            </Text>
          );
        })}
      </Text>
    );
  }

  if (line.role === "tool") {
    // Header lines start with "> ", body lines with "  "
    const isHeader = line.content.startsWith("> ");
    return (
      <Text
        key={line.key}
        color={isHeader ? (palette?.accent_dim ?? "yellow") : (palette?.primary_dim ?? "gray")}
        bold={isHeader}
      >
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
