/**
 * Nameplate — one-line replacement for the full Banner once the
 * user has logged a turn. The big wordmark + owl + info panel
 * lives at the top of the transcript until the first message
 * lands; after that, every following render uses Nameplate
 * instead so the conversation gets the screen real estate it
 * deserves.
 *
 * The Nameplate carries just enough identity to remind the user
 * which model/theme they're talking to without taking more than
 * one row of vertical space.
 */

import { Box, Text } from "ink";
import React from "react";

import type { BannerEvent, ThemePalette } from "../transport/protocol.js";

interface NameplateProps {
  banner: BannerEvent;
  palette: ThemePalette;
}

export function Nameplate({
  banner,
  palette,
}: NameplateProps): React.JSX.Element {
  return (
    <Box>
      <Text bold color={palette.primary}>
        ██ athena
      </Text>
      <Text color={palette.primary_dim}> · </Text>
      <Text color={palette.accent}>{banner.model}</Text>
      <Text color={palette.primary_dim}> · </Text>
      <Text color={palette.primary}>{palette.name}</Text>
    </Box>
  );
}
