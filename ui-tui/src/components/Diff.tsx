/**
 * <Diff> — render a unified-diff string with +/- coloring.
 *
 * Used by <Transcript> to render Edit / patch_apply tool results.
 * Detection is loose: if a tool result contains lines starting with
 * "+++", "---", "@@", or many "+"/"-" lines, treat as diff.
 */

import React from "react";
import { Box, Text } from "ink";

interface Props {
  text: string;
  addColor?: string;
  removeColor?: string;
  hunkColor?: string;
}

export function Diff({
  text, addColor = "green", removeColor = "red", hunkColor = "cyan",
}: Props): React.JSX.Element {
  const lines = text.split("\n");
  return (
    <Box flexDirection="column">
      {lines.map((ln, i) => {
        if (ln.startsWith("+++") || ln.startsWith("---")) {
          return <Text key={i} bold dimColor>{ln}</Text>;
        }
        if (ln.startsWith("@@")) {
          return <Text key={i} color={hunkColor}>{ln}</Text>;
        }
        if (ln.startsWith("+")) {
          return <Text key={i} color={addColor}>{ln}</Text>;
        }
        if (ln.startsWith("-")) {
          return <Text key={i} color={removeColor}>{ln}</Text>;
        }
        return <Text key={i} dimColor>{ln}</Text>;
      })}
    </Box>
  );
}

/** Heuristic: does this text look like a unified diff? */
export function looksLikeDiff(text: string): boolean {
  // Count diff-marker lines; require at least 3 OR a header line.
  const lines = text.split("\n");
  if (lines.some((ln) => ln.startsWith("@@") || ln.startsWith("--- a/") || ln.startsWith("+++ b/"))) {
    return true;
  }
  let markers = 0;
  for (const ln of lines) {
    if (ln.startsWith("+") || ln.startsWith("-")) markers++;
    if (markers >= 3) return true;
  }
  return false;
}
