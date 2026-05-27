/**
 * AskQuestionOverlay — multi-question multiple-choice prompt.
 *
 * Mirrors Claude Code's AskUserQuestion popup. The agent ships an
 * AskQuestionRequest; this owns the whole keyboard until answered.
 *
 * Layout per question:
 *
 *   ── header (when present) ──
 *   question text
 *     ▸ 1. Label — description (highlighted = selected)
 *       2. Other label — description
 *       ...
 *       N. Other (type custom)        ← always last
 *
 * Multiple questions render stacked, each with its own selector.
 *
 * Keys:
 *   ↑/↓     navigate options within the focused question
 *   Tab     move focus to the next question
 *   Space   (multiSelect only) toggle the focused option
 *   1-9     pick option by number (single-select shortcut)
 *   Enter   submit all answers; questions with no selection report
 *           "(no answer)"
 *   Esc     cancel — agent gets a "cancelled" sentinel
 *   c       open custom-text input for the last option ("Other")
 *
 * For now the custom-text path is a simplification: pressing "c"
 * picks the "Other" slot but with an empty answer. A future
 * iteration could open an inline input. Today the model gets
 * an empty answer and can prompt again if needed.
 */

import React from "react";
import { Box, Text } from "ink";

import type {
  AskQuestionEntry, ThemePalette,
} from "../transport/protocol.js";


interface Props {
  questions: AskQuestionEntry[];
  /** Index of the currently-focused question (0-based). Tab cycles. */
  focusedIdx: number;
  /** Per-question selection state:
   *   single-select: number | null (option index, 0-based; null = no answer)
   *   multi-select: number[] (zero or more option indices)
   * Custom "Other" is represented as index === options.length. */
  selections: Array<number | number[] | null>;
  palette: ThemePalette;
}


export function AskQuestionOverlay({
  questions, focusedIdx, selections, palette,
}: Props): React.JSX.Element {
  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={palette.accent}
      paddingX={1}
    >
      <Box marginBottom={1}>
        <Text color={palette.accent} bold>
          ? Athena needs your input
        </Text>
        <Text color={palette.primary_faint}>
          {"   "}↑↓ pick · Tab next question · Enter send · Esc cancel
        </Text>
      </Box>
      {questions.map((q, qi) => (
        <Box key={qi} flexDirection="column" marginBottom={1}>
          {q.header && (
            <Text color={palette.accent_dim}>── {q.header} ──</Text>
          )}
          <Text bold color={qi === focusedIdx ? palette.accent : palette.primary}>
            {qi === focusedIdx ? "▸ " : "  "}{q.question}
          </Text>
          {renderOptions(q, qi, focusedIdx, selections[qi], palette)}
        </Box>
      ))}
    </Box>
  );
}


function renderOptions(
  q: AskQuestionEntry,
  qi: number,
  focusedIdx: number,
  sel: number | number[] | null,
  palette: ThemePalette,
): React.JSX.Element {
  const opts = q.options ?? [];
  const total = opts.length;  // index ``total`` = the "Other" slot
  const isFocused = qi === focusedIdx;
  const multi = !!q.multiSelect;

  const isSelected = (idx: number): boolean => {
    if (sel === null) return false;
    if (Array.isArray(sel)) return sel.includes(idx);
    return sel === idx;
  };

  const rows: React.JSX.Element[] = [];
  for (let i = 0; i < total; i++) {
    const opt = opts[i];
    rows.push(
      <Box key={i}>
        <Text color={palette.primary_faint}>{"    "}</Text>
        <Text color={isSelected(i) ? palette.accent : palette.primary_dim}>
          {multi ? (isSelected(i) ? "[x] " : "[ ] ") : (isSelected(i) ? "▸ " : "  ")}
        </Text>
        <Text color={isSelected(i) ? palette.accent : palette.primary_dim} bold={isSelected(i)}>
          {i + 1}. {opt.label}
        </Text>
        <Text color={palette.primary_faint}>{"  — "}{opt.description}</Text>
      </Box>,
    );
  }
  // "Other (type custom)" — always last
  rows.push(
    <Box key="other">
      <Text color={palette.primary_faint}>{"    "}</Text>
      <Text color={isSelected(total) ? palette.accent : palette.primary_dim}>
        {multi ? (isSelected(total) ? "[x] " : "[ ] ") : (isSelected(total) ? "▸ " : "  ")}
      </Text>
      <Text color={isSelected(total) ? palette.accent : palette.primary_dim} italic>
        {total + 1}. Other (free-form)
      </Text>
    </Box>,
  );
  // When focused, show the cursor hint at the bottom
  if (isFocused) {
    rows.push(
      <Text key="hint" color={palette.primary_faint} dimColor>
        {"      "}↑↓ to move{multi ? " · Space to toggle" : ""}
      </Text>,
    );
  }
  return <Box flexDirection="column">{rows}</Box>;
}
