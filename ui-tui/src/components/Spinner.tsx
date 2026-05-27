/**
 * <Spinner> — animated glyph rotation for in-flight tool calls.
 *
 * Default: ◐◓◑◒ at 8Hz (125ms per frame), the four-phase
 * half-moon. Smooth and visually quiet — doesn\'t shout for
 * attention but lets the eye see "still working."
 *
 * Variant `dots` for a tighter spinner: ⣾⣽⣻⢿⡿⣟⣯⣷ at 12Hz.
 *
 * Once the work completes the host renders `✓` or `✗` directly;
 * Spinner doesn\'t handle terminal states.
 */

import React from "react";
import { Text } from "ink";

import { useTicker } from "../hooks/useTicker.js";

const HALF_MOONS = ["◐", "◓", "◑", "◒"];
const DOTS = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"];

interface Props {
  variant?: "half_moon" | "dots";
  color?: string;
}

export function Spinner({ variant = "half_moon", color }: Props): React.JSX.Element {
  const frames = variant === "dots" ? DOTS : HALF_MOONS;
  const interval = variant === "dots" ? 83 : 125;  // 12Hz / 8Hz
  const tick = useTicker(interval);
  const glyph = frames[tick % frames.length];
  return <Text color={color}>{glyph}</Text>;
}
