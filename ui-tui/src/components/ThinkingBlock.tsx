/**
 * <ThinkingBlock> — collapsed reasoning trace, expandable on demand.
 *
 * The protocol\'s stream filter strips <think>...</think> blocks
 * from the displayed text. Step 10 surfaces them as a folded row:
 *
 *   ▸ thinking (1.3s, ~412 tokens)
 *
 * Tab expands to show the full reasoning text. Tab again collapses.
 *
 * Currently this component just renders the collapsed state — the
 * expand/collapse interaction is owned by App via state (added in
 * a follow-on commit once we wire the toggle).
 */

import React from "react";
import { Box, Text } from "ink";

interface Props {
  /** The reasoning text (may be multi-paragraph). */
  thinking: string;
  /** Whether to render expanded. */
  expanded?: boolean;
  /** Color for the chevron and label. */
  accentColor?: string;
  dimColor?: string;
}

export function ThinkingBlock({
  thinking, expanded = false, accentColor, dimColor,
}: Props): React.JSX.Element {
  const tokenEstimate = Math.ceil(thinking.split(/\s+/).length / 0.75);
  const lineCount = thinking.split("\n").length;
  if (!expanded) {
    return (
      <Text dimColor color={accentColor}>
        ▸ thinking ({lineCount} line{lineCount === 1 ? "" : "s"}, ~{tokenEstimate} tokens) — Tab to expand
      </Text>
    );
  }
  return (
    <Box flexDirection="column">
      <Text dimColor color={accentColor}>
        ▾ thinking — Tab to collapse
      </Text>
      {thinking.split("\n").map((ln, i) => (
        <Text key={i} dimColor italic color={dimColor}>
          │ {ln}
        </Text>
      ))}
    </Box>
  );
}
