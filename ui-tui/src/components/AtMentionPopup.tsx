/**
 * AtMentionPopup — file-path completion menu, shown below the
 * composer when the user is typing an @-mention.
 *
 * Same visual style + keyboard semantics as SlashPopup: arrow keys
 * navigate, Tab accepts. Owner (main.tsx) computes the matches via
 * matchWorkspaceFiles and passes them in.
 */

import React from "react";
import { Box, Text } from "ink";

import type { ThemePalette } from "../transport/protocol.js";


interface AtMentionPopupProps {
  matches: string[];
  selectedIdx: number;
  palette: ThemePalette;
}

export function AtMentionPopup({
  matches, selectedIdx, palette,
}: AtMentionPopupProps): React.JSX.Element | null {
  if (matches.length === 0) return null;
  const sel = Math.min(Math.max(0, selectedIdx), matches.length - 1);
  return (
    <Box flexDirection="column" marginLeft={2}>
      {matches.map((m, i) => {
        const isSel = i === sel;
        return (
          <Box key={m}>
            <Text color={isSel ? palette.accent : palette.primary_dim}>
              {isSel ? "▸ " : "  "}
            </Text>
            <Text
              color={isSel ? palette.accent : palette.primary_dim}
              bold={isSel}
            >
              {m}
            </Text>
          </Box>
        );
      })}
    </Box>
  );
}
