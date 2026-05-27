/**
 * SlashPopup — completion menu shown below the composer input.
 *
 * Renders when the input buffer starts with "/" and matches at least
 * one known slash command. Filtered as the user types. Up/down
 * navigate (overriding history nav when this is visible), Tab
 * accepts the selected completion. The popup also lets new users
 * discover what commands exist — today, you have to know names.
 *
 * The command catalog is static here; if it ever drifts from
 * ``athena/commands/help_cmd.py``, the SLASH_COMMANDS sweep test
 * catches the drift.
 */

import React from "react";
import { Box, Text } from "ink";

import type { ThemePalette } from "../transport/protocol.js";

/** One command entry. ``name`` is what we replace the buffer with on
 * accept; ``description`` is the dim hint shown next to it. */
export interface SlashCommand {
  name: string;
  description: string;
}

/** Source of truth — mirrors athena/commands/help_cmd.py SLASH_HELP.
 * Parametric over which name expands to which command. */
export const SLASH_COMMANDS: SlashCommand[] = [
  { name: "/help",            description: "show slash-command reference" },
  { name: "/model",           description: "switch model (arg: NAME)" },
  { name: "/models",          description: "list available Ollama models" },
  { name: "/tools",           description: "list registered tools (built-in + MCP)" },
  { name: "/mcp",             description: "list MCP servers (or 'logs NAME' for stderr)" },
  { name: "/clear",           description: "reset conversation (keeps system prompt)" },
  { name: "/cost",            description: "token usage + elapsed time" },
  { name: "/status",          description: "session snapshot (model, tokens, retries)" },
  { name: "/save",            description: "save transcript (arg: file path)" },
  { name: "/dump",            description: "print the live system prompt" },
  { name: "/cwd",             description: "show or change workspace (arg: path)" },
  { name: "/init",            description: "generate ATHENA.md from workspace survey" },
  { name: "/review",          description: "review pending changes (arg: git ref)" },
  { name: "/security-review", description: "security-focused review of pending changes" },
  { name: "/loop",            description: "run a prompt on a timer (args: INTERVAL CMD)" },
  { name: "/loop-stop",       description: "stop a running /loop" },
  { name: "/checkpoint",      description: "snapshot workspace + agent state (arg: name)" },
  { name: "/checkpoints",     description: "list checkpoints in this session" },
  { name: "/compact",         description: "summarize history and replace it" },
  { name: "/resume",          description: "resume a saved transcript (arg: file)" },
  { name: "/memory",          description: "inspect/edit persistent memory (subcmd)" },
  { name: "/plan",            description: "enter plan mode (read-only investigation)" },
  { name: "/plan-exit",       description: "leave plan mode without executing" },
  { name: "/steer",           description: "queue MSG for next prompt (or 'clear')" },
  { name: "/queue",           description: "list pending steers" },
  { name: "/goal",            description: "set/pause/resume/inspect/clear active goal" },
  { name: "/subgoal",         description: "append (arg: MSG) or 'done' the next subgoal" },
  { name: "/board",           description: "render the kanban (or 'clear' to wipe)" },
  { name: "/video",           description: "video backends: list/set/clear" },
  { name: "/theme",           description: "TUI palette: list, 'set NAME', or 'save'" },
  { name: "/hooks",           description: "list configured hooks" },
  { name: "/exit",            description: "quit" },
];

/** Filter the catalog against ``query`` (case-insensitive prefix
 * match on the command name). Returns at most ``limit`` matches. */
export function matchSlashCommands(
  query: string,
  limit = 7,
): SlashCommand[] {
  const q = query.toLowerCase();
  if (!q.startsWith("/")) return [];
  // Match anything whose name starts with the query (prefix match).
  // Empty query "/" lists everything.
  const hits = SLASH_COMMANDS.filter((c) =>
    c.name.toLowerCase().startsWith(q),
  );
  return hits.slice(0, limit);
}

interface SlashPopupProps {
  /** Current editor text — used to filter the list. */
  query: string;
  /** Which entry is highlighted (clamped to matches.length-1). */
  selectedIdx: number;
  palette: ThemePalette;
}

export function SlashPopup({
  query, selectedIdx, palette,
}: SlashPopupProps): React.JSX.Element | null {
  const matches = matchSlashCommands(query);
  if (matches.length === 0) return null;
  // Clamp selection in case caller-side state is briefly out of sync
  // with the filtered list shrinking under it.
  const sel = Math.min(Math.max(0, selectedIdx), matches.length - 1);
  // Width of the widest name so descriptions line up.
  const nameWidth = matches.reduce(
    (w, m) => Math.max(w, m.name.length),
    0,
  );
  return (
    <Box flexDirection="column" marginLeft={2}>
      {matches.map((m, i) => {
        const isSel = i === sel;
        const namePadded = m.name.padEnd(nameWidth + 2);
        return (
          <Box key={m.name}>
            <Text color={isSel ? palette.accent : palette.primary_dim}>
              {isSel ? "▸ " : "  "}
            </Text>
            <Text
              color={isSel ? palette.accent : palette.primary_dim}
              bold={isSel}
            >
              {namePadded}
            </Text>
            <Text color={palette.primary_faint}>{m.description}</Text>
          </Box>
        );
      })}
    </Box>
  );
}

/** Return the completion text for accepting ``selected``: the full
 * command name + a single trailing space (so the user can immediately
 * type arguments without backspacing or pressing space). */
export function completionText(selected: SlashCommand): string {
  return selected.name + " ";
}
