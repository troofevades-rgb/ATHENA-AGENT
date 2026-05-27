/**
 * <Composer> — the pinned bottom region.
 *
 * Layout:
 *   tool activity lane (when active)
 *   ephemeral flash (when present)
 *   confirm overlay (when present) OR prompt input (default)
 *   status bar
 *
 * Owns no state — input value/cursor come from useLineEditor in
 * the App, passed through as props.
 */

import React from "react";
import { Box, Text } from "ink";

import { AskQuestionOverlay } from "./AskQuestionOverlay.js";
import { AtMentionPopup } from "./AtMentionPopup.js";
import { SlashPopup } from "./SlashPopup.js";
import { StatusBar } from "./StatusBar.js";
import { StuckIndicator } from "./StuckIndicator.js";
import { ToolLaneRow } from "./ToolLaneRow.js";
import type {
  BannerEvent, ConfirmRequestEvent, StatusFlashEvent, StatusUpdateEvent,
} from "../transport/protocol.js";
import type { ToolLaneEntry, TuiState } from "../state/types.js";

interface Props {
  banner: BannerEvent | null;
  status: StatusUpdateEvent | null;
  toolLane: ToolLaneEntry[];
  flash: StatusFlashEvent | null;
  confirmReq: ConfirmRequestEvent | null;
  inputText: string;
  cursorPos: number;
  /** Token-rate sparkline data for StatusBar. */
  tpsHistory?: number[];
  tpsCurrent?: number;
  /** Full TuiState — passed to the stalled-turn detector so it can
   * read streamId / toolLane / _lastProgressMs / _pendingUserInputSince
   * without each child needing its own selector. */
  state?: TuiState;
  /** Index of the highlighted entry in the slash-completion popup.
   * Owned by main.tsx so keyboard handling can navigate it. The
   * popup itself filters off ``inputText``. */
  slashSelectedIdx?: number;
  /** Terminal width — forwarded to StatusBar's narrow-width
   * segment-dropping logic. */
  termCols?: number;
  /** @-mention popup state. ``matches`` empty means popup hidden. */
  atMatches?: string[];
  atSelectedIdx?: number;
  /** Reverse-search state. Non-null means we're in Ctrl+R mode and
   * the composer shows ``(reverse-i-search)`query`: match`` instead
   * of the normal input box. */
  reverseSearch?: { query: string; match: string | null } | null;
  /** AskUserQuestion overlay state — questions + per-question
   * selections + which question is focused. Owns the keyboard. */
  askFocusedIdx?: number;
  askSelections?: Array<number | number[] | null>;
}

export function Composer({
  banner, status, toolLane, flash, confirmReq, inputText, cursorPos,
  tpsHistory, tpsCurrent, state, slashSelectedIdx = 0, termCols,
  atMatches = [], atSelectedIdx = 0, reverseSearch = null,
  askFocusedIdx = 0, askSelections = [],
}: Props): React.JSX.Element {
  const palette = banner?.palette ?? undefined;
  const promptColor = palette?.primary ?? "green";
  // Plan-mode visual treatment: tint the composer border and show a
  // banner row so the user can't forget that write tools are
  // blocked. Status comes from the periodic StatusUpdateEvent.
  const inPlanMode = status?.plan_mode === true;
  const composerBorderColor = inPlanMode
    ? (palette?.accent ?? "magenta")
    : (palette?.primary_faint ?? "gray");

  return (
    <Box flexDirection="column">
      {toolLane.length > 0 && (
        <Box flexDirection="column" marginBottom={1}>
          {toolLane.map((t) => (
            <ToolLaneRow
              key={t.id}
              tool={t.tool}
              args={t.args}
              startedAtMs={t.startedAtMs}
              palette={palette}
            />
          ))}
        </Box>
      )}
      {flash && (
        <Box marginBottom={0}>
          <Text
            dimColor
            italic
            color={
              flash.level === "warn"
                ? "yellow"
                : palette?.primary_dim ?? "gray"
            }
          >
            {flash.level === "warn" ? "! " : "· "}
            {flash.text}
          </Text>
        </Box>
      )}
      {state?.askReq && !confirmReq ? (
        <AskQuestionOverlay
          questions={state.askReq.questions}
          focusedIdx={askFocusedIdx}
          selections={askSelections}
          palette={palette!}
        />
      ) : reverseSearch && !confirmReq ? (
        // Reverse-incremental search overlay — replaces the normal
        // input until accepted / cancelled. Format mirrors shell
        // convention: (reverse-i-search)`query`: match
        <Box
          flexDirection="column"
          borderStyle="round"
          borderColor={palette?.accent ?? "yellow"}
          paddingX={1}
        >
          <Box>
            <Text color={palette?.primary_faint ?? "gray"}>
              {"(reverse-i-search)`"}
            </Text>
            <Text color={palette?.accent ?? "yellow"} bold>
              {reverseSearch.query}
            </Text>
            <Text color={palette?.primary_faint ?? "gray"}>{"`: "}</Text>
            <Text color={
              reverseSearch.match
                ? "white"
                : (palette?.primary_faint ?? "gray")
            }>
              {reverseSearch.match ?? "(no match)"}
            </Text>
          </Box>
          <Text color={palette?.primary_dim ?? "gray"} dimColor>
            Ctrl+R: older  ·  Enter: accept  ·  Esc: cancel  ·  Backspace: shrink query
          </Text>
        </Box>
      ) : confirmReq ? (
        <Box
          flexDirection="column"
          borderStyle="round"
          borderColor={palette?.accent ?? "yellow"}
          paddingX={1}
        >
          {confirmReq.tool_name && (
            <Text color={palette?.accent_dim ?? "yellow"}>
              ── {confirmReq.tool_name} ──
            </Text>
          )}
          {confirmReq.preview && renderConfirmPreview(
            confirmReq.preview,
            confirmReq.preview_kind ?? "text",
            palette,
          )}
          <Text bold color={palette?.accent ?? "yellow"}>
            ? {confirmReq.prompt}
          </Text>
          <Text color={palette?.primary_dim ?? "gray"}>
            {confirmReq.default ? "[Y/n]" : "[y/N]"}{" "}
            <Text dimColor>press y / n / Enter (default) / Esc</Text>
          </Text>
        </Box>
      ) : (
        // Bordered card frames the prompt input so it reads as a
        // proper input field. Border tints to accent in plan mode
        // (read-only) so the user has a constant visual reminder.
        //
        // Multi-line: the buffer may contain \n characters (Shift+Enter
        // inserts them). Each logical line renders as its own row;
        // continuation rows are indented to align under the ▸▸ marker
        // on the first row.
        <Box flexDirection="column">
          {inPlanMode && (
            <Box marginBottom={0}>
              <Text color={palette?.accent ?? "magenta"} bold>
                ◆ plan mode
              </Text>
              <Text color={palette?.primary_faint ?? "gray"}>
                {" — write/edit/bash blocked. /plan-exit to leave."}
              </Text>
            </Box>
          )}
          <Box
            flexDirection="column"
            borderStyle="round"
            borderColor={composerBorderColor}
            paddingX={1}
          >
            {renderMultiLineInput(
              inputText, cursorPos, promptColor,
            )}
          </Box>
        </Box>
      )}
      {/* Slash-command completion popup — only when the buffer
          starts with "/" and at least one command matches. Renders
          between the input box and the status bar. */}
      {palette && !confirmReq && inputText.startsWith("/") && (
        <SlashPopup
          query={inputText}
          selectedIdx={slashSelectedIdx}
          palette={palette}
        />
      )}
      {/* @-mention file-path popup — shown when the user is typing
          @<partial> and at least one workspace file matches. */}
      {palette && !confirmReq && atMatches.length > 0 && (
        <AtMentionPopup
          matches={atMatches}
          selectedIdx={atSelectedIdx}
          palette={palette}
        />
      )}
      {palette && state && (
        <StuckIndicator state={state} palette={palette} />
      )}
      {palette && (
        <StatusBar
          status={status}
          palette={palette}
          tpsHistory={tpsHistory}
          tpsCurrent={tpsCurrent}
          termCols={termCols}
        />
      )}
    </Box>
  );
}


/**
 * Render the rich preview body of a ConfirmRequest. ``kind`` picks
 * the visual treatment: command (cyan, mono-feel), diff (+/- color),
 * file (path-then-content), text (dim plain).
 *
 * Capped at 15 lines on the TUI side too (Python already capped
 * Write/Edit previews) so a giant Bash command or file preview
 * doesn't blow out the composer height.
 */
function renderConfirmPreview(
  preview: string,
  kind: "command" | "diff" | "file" | "text",
  palette: { accent?: string; accent_dim?: string; primary_dim?: string; primary_faint?: string } | undefined,
): React.JSX.Element {
  const allLines = preview.split("\n");
  const MAX = 15;
  const lines = allLines.slice(0, MAX);
  const overflow = allLines.length - lines.length;

  if (kind === "command") {
    return (
      <Box flexDirection="column" marginY={1}>
        {lines.map((line, i) => (
          <Text key={i} color={palette?.accent ?? "cyan"}>
            $ {line}
          </Text>
        ))}
        {overflow > 0 && (
          <Text color={palette?.primary_faint ?? "gray"}>
            … ({overflow} more lines)
          </Text>
        )}
      </Box>
    );
  }
  if (kind === "diff") {
    return (
      <Box flexDirection="column" marginY={1}>
        {lines.map((line, i) => {
          let color: string | undefined;
          let bold = false;
          if (line.startsWith("+++") || line.startsWith("---")) {
            color = palette?.primary_faint ?? "gray";
            bold = true;
          } else if (line.startsWith("@@")) {
            color = palette?.accent_dim ?? "yellow";
            bold = true;
          } else if (line.startsWith("+")) {
            color = "green";
          } else if (line.startsWith("-")) {
            color = "red";
          } else {
            color = palette?.primary_dim ?? "gray";
          }
          return (
            <Text key={i} color={color} bold={bold}>{line}</Text>
          );
        })}
        {overflow > 0 && (
          <Text color={palette?.primary_faint ?? "gray"}>
            … ({overflow} more lines)
          </Text>
        )}
      </Box>
    );
  }
  if (kind === "file") {
    // First line: path. Rest: content preview.
    return (
      <Box flexDirection="column" marginY={1}>
        {lines.map((line, i) => (
          <Text
            key={i}
            color={i === 0 ? (palette?.accent ?? "cyan") : (palette?.primary_dim ?? "gray")}
            bold={i === 0}
          >
            {line}
          </Text>
        ))}
        {overflow > 0 && (
          <Text color={palette?.primary_faint ?? "gray"}>
            … ({overflow} more lines)
          </Text>
        )}
      </Box>
    );
  }
  // text (default)
  return (
    <Box flexDirection="column" marginY={1}>
      {lines.map((line, i) => (
        <Text key={i} color={palette?.primary_dim ?? "gray"}>
          {line}
        </Text>
      ))}
      {overflow > 0 && (
        <Text color={palette?.primary_faint ?? "gray"}>
          … ({overflow} more lines)
        </Text>
      )}
    </Box>
  );
}


/**
 * Render the input buffer as one row per logical line, with the
 * cursor highlighted on whichever line contains ``cursorPos``.
 * First line gets the ▸▸ prompt marker; continuation lines are
 * indented 3 columns so they visually align under it.
 */
function renderMultiLineInput(
  text: string, cursor: number, promptColor: string,
): React.JSX.Element[] {
  const lines = text.split("\n");
  // No newlines, no cursor edge case: keep the dense single-line form
  // (slightly tighter than the multi-line path).
  const out: React.JSX.Element[] = [];
  let charsSoFar = 0;
  for (let lineIdx = 0; lineIdx < lines.length; lineIdx++) {
    const line = lines[lineIdx];
    const lineStart = charsSoFar;
    const lineEnd = lineStart + line.length;
    // Cursor is "in" this line if cursorPos is between lineStart and
    // lineEnd inclusive — being AT the trailing newline counts as
    // belonging to the next line (handled by the loop progression).
    const cursorInLine = (cursor >= lineStart && cursor <= lineEnd)
      ? cursor - lineStart
      : -1;
    charsSoFar = lineEnd + 1;  // +1 for the consumed newline

    const prefix = lineIdx === 0
      ? <Text color={promptColor}>{"▸▸ "}</Text>
      : <Text>{"   "}</Text>;  // align with ▸▸

    if (cursorInLine === -1) {
      out.push(
        <Box key={lineIdx}>
          {prefix}
          <Text>{line}</Text>
        </Box>,
      );
      continue;
    }
    // Cursor lands somewhere on this line.
    out.push(
      <Box key={lineIdx}>
        {prefix}
        <Text>{line.slice(0, cursorInLine)}</Text>
        {cursorInLine < line.length ? (
          <>
            <Text color={promptColor} inverse>{line.charAt(cursorInLine)}</Text>
            <Text>{line.slice(cursorInLine + 1)}</Text>
          </>
        ) : (
          <Text color={promptColor} inverse>{" "}</Text>
        )}
      </Box>,
    );
  }
  return out;
}
